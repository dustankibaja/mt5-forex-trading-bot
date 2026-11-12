package jforex;
import com.dukascopy.api.*;
import java.nio.file.Files;
import java.util.Collections;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

/** EUR/USD diagnostic recorder. Start locally in the JForex desktop DEMO session. */
@RequiresFullAccess
public final class EmtifizeDemoCapture implements IStrategy {
    private Spool spool;

    @Override public void onStart(IContext context) throws JFException {
        if (context.getEngine().getType() != IEngine.Type.DEMO)
            throw new JFException("EUR/USD diagnostic capture requires a DEMO account");
        try {
            Path directory = Paths.get(System.getenv("LOCALAPPDATA"), "EmtifizeResearch", "JForex");
            if (!Files.isDirectory(directory)) throw new IOException("Private capture folder missing");
            Path file = directory.resolve("diagnostic-desktop-" + UUID.randomUUID() + ".tsv");
            spool = new Spool(file, false, 8192);
            spool.event("strategy_started", 0);
            spool.event("connected", 0);
            spool.event("demo_account_connected", 0);
            context.setSubscribedInstruments(Collections.singleton(Instrument.EURUSD), true);
            spool.event("subscribed", 0);
            context.getConsole().getOut().println("EUR/USD diagnostic capture started.");
        } catch (Exception failure) {
            if (spool != null) {
                spool.event("collector_fault", 0);
                onStop();
            }
            throw new JFException("Capture startup failed: " + failure.getClass().getSimpleName());
        }
    }

    @Override public void onTick(Instrument instrument, ITick tick) throws JFException {
        if (spool == null || instrument != Instrument.EURUSD) return;
        try { spool.check(); }
        catch (IOException failure) { throw new JFException("Capture write failed"); }
        spool.event("tick", tick.getTime(), tick.getBid(), tick.getAsk());
    }

    @Override public void onBar(Instrument instrument, Period period, IBar ask, IBar bid) {
        if (spool == null || instrument != Instrument.EURUSD || !Period.ONE_HOUR.equals(period)) return;
        if (ask == null || bid == null || ask.getTime() != bid.getTime()) {
            spool.event("gap", 0);
            return;
        }
        spool.event("h1", bid.getTime(), bid.getOpen(), bid.getHigh(), bid.getLow(), bid.getClose(),
                    ask.getOpen(), ask.getHigh(), ask.getLow(), ask.getClose());
    }

    @Override public void onStop() throws JFException {
        if (spool == null) return;
        try {
            spool.event("strategy_stopped", 0);
            spool.close();
        } catch (Exception failure) {
            throw new JFException("Capture close failed");
        } finally {
            spool = null;
        }
    }

    @Override public void onMessage(IMessage ignored) {}
    @Override public void onAccount(IAccount ignored) {}

    /** Single-writer, bounded callback spool. Output directory must be user-private. */
    private static final class Spool implements AutoCloseable {
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
            try (FileChannel output = channel) {
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

}
