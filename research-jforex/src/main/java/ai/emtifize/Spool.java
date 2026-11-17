package ai.emtifize;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

/** Single-writer, bounded callback spool. Output directory must be user-private. */
final class Spool implements AutoCloseable {
    private final String run = UUID.randomUUID().toString();
    private final String source;
    private final ArrayBlockingQueue<String> queue;
    private final Thread writer;
    private final FileChannel channel;
    private volatile IOException failure;
    private boolean closed;
    private volatile boolean finished;
    private long sequence, dropped;
    private final long origin = System.nanoTime();

    Spool(Path file, boolean fixture, int capacity) throws IOException {
        source = fixture ? "synthetic" : "jforex_demo";
        queue = new ArrayBlockingQueue<>(capacity);
        channel = FileChannel.open(file, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        writer = new Thread(this::write, "research-spool");
        writer.start();
    }

    synchronized void event(String kind, long raw, double... values) {
        if (closed || failure != null) return;
        if (!queue.offer(line(kind, raw, values))) dropped++;
    }

    private String line(String kind, long raw, double[] values) {
        long host = System.currentTimeMillis();
        long monotonic = System.nanoTime() - origin;
        StringBuilder out = new StringBuilder("1\t").append(source).append("\tcollector-1\t")
            .append(run).append('\t').append(++sequence).append('\t').append(kind).append('\t')
            .append(raw).append('\t').append(host).append('\t').append(monotonic).append('\t')
            .append(dropped).append("\tEURUSD");
        for (double value : values) out.append('\t').append(value);
        return out.append('\n').toString();
    }

    private void write() {
        try (channel) {
            while (!finished || !queue.isEmpty()) {
                String item = queue.poll(100, TimeUnit.MILLISECONDS);
                if (item == null) continue;
                int batch = 0;
                do {
                    ByteBuffer data = StandardCharsets.US_ASCII.encode(item);
                    while (data.hasRemaining()) channel.write(data);
                    item = ++batch < 256 ? queue.poll() : null;
                } while (item != null);
                channel.force(false);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            failure = new IOException("spool interrupted", e);
        } catch (IOException e) {
            failure = e;
        }
    }

    void check() throws IOException {
        if (failure != null) throw failure;
    }

    @Override public synchronized void close() throws Exception {
        if (closed) return;
        closed = true;
        String end = line("end", 0, new double[0]);
        while (!queue.offer(end, 100, TimeUnit.MILLISECONDS)) check();
        finished = true;
        writer.join();
        check();
    }
}
