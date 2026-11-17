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
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** EUR/USD diagnostic recorder. Start locally in the JForex desktop DEMO session. */
@RequiresFullAccess
public final class EmtifizeDemoCapture implements IStrategy {
    private Spool spool;
    private ScheduledExecutorService heartbeat;
    private boolean connected;
    private boolean subscribed;
    private boolean accountConnected;
    private IContext desktopContext;
    private String accountIdentity;
    private IHistory history;
    private IConsole contextConsole;
    private Path warmupFile;
    private boolean warmupPending = true;
    @Configurable("Retrieve historical warm-up once")
    public boolean retrieveWarmup = true;

    @Override public void onStart(IContext context) throws JFException {
        if (context.getEngine().getType() != IEngine.Type.DEMO)
            throw new JFException("EUR/USD diagnostic capture requires a DEMO account");
        IAccount account = context.getAccount();
        if (account == null || account.getAccountId() == null || account.getAccountId().isEmpty())
            throw new JFException("Cannot bind the DEMO account");
        desktopContext = context;
        accountIdentity = account.getAccountId();
        accountConnected = account.isConnected();
        try {
            Path directory = Paths.get(System.getenv("LOCALAPPDATA"), "EmtifizeResearch", "JForex");
            if (!Files.isDirectory(directory)) throw new IOException("Private capture folder missing");
            Path file = directory.resolve("diagnostic-desktop-" + UUID.randomUUID() + ".tsv");
            history = context.getHistory();
            contextConsole = context.getConsole();
            warmupFile = file.resolveSibling(file.getFileName() + ".warmup.csv");
            spool = new Spool(file, false, 8192);
            spool.event("strategy_started", 0);
            spool.event("connected", 0);
            spool.event("demo_account_connected", 0);
            connected = true;
            context.setSubscribedInstruments(Collections.singleton(Instrument.EURUSD), true);
            if (!context.getSubscribedInstruments().contains(Instrument.EURUSD)) {
                spool.event("instrument_unavailable", 0);
                throw new JFException("EUR/USD subscription unavailable");
            }
            spool.event("subscribed", 0);
            subscribed = true;
            final Spool activeSpool = spool;
            heartbeat = Executors.newSingleThreadScheduledExecutor(task -> {
                Thread thread = new Thread(task, "emtifize-capture-heartbeat");
                thread.setDaemon(true);
                return thread;
            });
            heartbeat.scheduleWithFixedDelay(() -> activeSpool.event("heartbeat", 0), 15, 15,
                                             TimeUnit.SECONDS);
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
        if (!sameDemoAccount(desktopContext.getAccount())) return;
        if (!connected) {
            // Desktop can resume ticks before emitting a positive account callback.
            // The live tick and unchanged local DEMO binding prove feed recovery.
            connected = true;
            spool.event("connected", 0);
        }
        if (!subscribed) {
            spool.event("subscribed", 0);
            subscribed = true;
        }
        spool.event("tick", tick.getTime(), tick.getBid(), tick.getAsk());
        if (retrieveWarmup && warmupPending) {
            warmupPending = false;
            writeWarmup(tick.getTime());
        }
    }

    private void writeWarmup(long providerTime) {
        try {
            long cutoff = history.getPreviousBarStart(Period.ONE_HOUR, providerTime);
            java.util.List<IBar> bids = history.getBars(Instrument.EURUSD, Period.ONE_HOUR, OfferSide.BID,
                                                        Filter.WEEKENDS, 220, cutoff, 0);
            java.util.List<IBar> asks = history.getBars(Instrument.EURUSD, Period.ONE_HOUR, OfferSide.ASK,
                                                        Filter.WEEKENDS, 220, cutoff, 0);
            if (bids.size() != asks.size() || bids.size() < 211)
                throw new IOException("Incomplete warm-up pairs");
            StringBuilder csv = new StringBuilder("provenance,raw_open_ms,bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c\n");
            long previous = 0;
            for (int i = 0; i < bids.size(); i++) {
                IBar bid = bids.get(i), ask = asks.get(i);
                long opening = bid.getTime();
                if (opening != ask.getTime() || opening <= previous || opening % 3_600_000L != 0
                        || opening + 3_600_000L > providerTime)
                    throw new IOException("Invalid paired warm-up timestamps");
                previous = opening;
                csv.append("jforex_live_origin_warmup,").append(opening);
                appendPrices(csv, bid);
                appendPrices(csv, ask);
                csv.append('\n');
            }
            Files.write(warmupFile, csv.toString().getBytes(StandardCharsets.US_ASCII),
                        StandardOpenOption.CREATE_NEW);
            spool.event("warmup_written", 0);
        } catch (Exception failure) {
            spool.event("warmup_unavailable", 0);
            if (contextConsole != null)
                contextConsole.getErr().println("Historical warm-up unavailable: " + failure.getClass().getSimpleName());
        }
    }

    private static void appendPrices(StringBuilder csv, IBar bar) {
        for (double value : new double[]{bar.getOpen(), bar.getHigh(), bar.getLow(), bar.getClose()}) {
            if (!Double.isFinite(value) || value <= 0) throw new IllegalArgumentException("Invalid warm-up price");
            csv.append(',').append(value);
        }
    }

    @Override public void onBar(Instrument instrument, Period period, IBar ask, IBar bid) {
        if (spool == null || !connected || !subscribed || instrument != Instrument.EURUSD
                || !Period.ONE_HOUR.equals(period)) return;
        if (ask == null || bid == null || ask.getTime() != bid.getTime()) {
            spool.event("gap", 0);
            return;
        }
        spool.event("h1", bid.getTime(), bid.getOpen(), bid.getHigh(), bid.getLow(), bid.getClose(),
                    ask.getOpen(), ask.getHigh(), ask.getLow(), ask.getClose());
    }

    @Override public void onStop() throws JFException {
        if (heartbeat != null) heartbeat.shutdownNow();
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
    @Override public void onAccount(IAccount account) {
        if (spool == null || !sameDemoAccount(account)) return;
        boolean reportedConnected = account.isConnected();
        if (accountConnected && !reportedConnected) {
            connected = false;
            subscribed = false;
            spool.event("disconnected", 0);
        }
        accountConnected = reportedConnected;
    }

    private boolean sameDemoAccount(IAccount account) {
        return account != null && desktopContext.getEngine().getType() == IEngine.Type.DEMO
                && accountIdentity.equals(account.getAccountId());
    }

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
            StringBuilder out = new StringBuilder("1\t").append(source).append("\tcollector-2\t")
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
