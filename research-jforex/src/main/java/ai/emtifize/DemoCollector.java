package ai.emtifize;

import com.dukascopy.api.*;
import com.dukascopy.api.system.*;
import java.io.Console;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.file.Path;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;
import java.util.Set;
import java.awt.GridLayout;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JPasswordField;

/** A fixed DEMO endpoint and one instrument. No order or account-state handling. */
public final class DemoCollector implements IStrategy {
    private static final String DEMO = "https://platform.dukascopy.com/demo_3/jforex_3.jnlp";
    private final Spool spool;
    private volatile boolean active;
    private volatile boolean authenticated;
    private IHistory history;
    private final Path warmup;
    private boolean warmupAttempted;

    DemoCollector(Spool spool, Path warmup) { this.spool = spool; this.warmup = warmup; }
    @Override public void onStart(IContext context) {
        spool.event("strategy_started", 0);
        history = context.getHistory();
        onAccount(context.getAccount());
    }
    @Override public void onStop() { spool.event("strategy_stopped", 0); }
    @Override public void onMessage(IMessage ignored) {}
    @Override public synchronized void onAccount(IAccount account) {
        boolean connected = account != null && account.isConnected();
        if (connected && !authenticated) spool.event("demo_account_connected", 0);
        authenticated = connected;
    }
    @Override public void onTick(Instrument instrument, ITick tick) {
        if (active && authenticated && instrument == Instrument.EURUSD) {
            spool.event("tick", tick.getTime(), tick.getBid(), tick.getAsk());
            if (warmup != null && !warmupAttempted) {
                warmupAttempted = true;
                writeWarmup(tick.getTime());
            }
        }
    }
    private void writeWarmup(long providerTime) {
        try {
            long cutoff = history.getBarStart(Period.ONE_HOUR, providerTime) - 1;
            var bids = history.getBars(Instrument.EURUSD, Period.ONE_HOUR, OfferSide.BID,
                                       Filter.WEEKENDS, 220, cutoff, 0);
            var asks = history.getBars(Instrument.EURUSD, Period.ONE_HOUR, OfferSide.ASK,
                                       Filter.WEEKENDS, 220, cutoff, 0);
            if (bids.size() != asks.size() || bids.size() < 211) throw new IllegalStateException();
            StringBuilder csv = new StringBuilder("provenance,raw_open_ms,bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c\n");
            long previous = 0;
            for (int i = 0; i < bids.size(); i++) {
                IBar b = bids.get(i), a = asks.get(i);
                if (b.getTime() != a.getTime() || b.getTime() <= previous || b.getTime() + 3_600_000L > providerTime)
                    throw new IllegalStateException();
                previous = b.getTime();
                csv.append("jforex_live_origin_warmup,").append(previous);
                for (double price : new double[]{b.getOpen(), b.getHigh(), b.getLow(), b.getClose(),
                                                a.getOpen(), a.getHigh(), a.getLow(), a.getClose()})
                    csv.append(',').append(price);
                csv.append('\n');
            }
            Files.writeString(warmup, csv, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            spool.event("warmup_written", 0);
        } catch (Exception failure) {
            spool.event("warmup_unavailable", 0);
        }
    }
    @Override public void onBar(Instrument instrument, Period period, IBar ask, IBar bid) {
        if (!active || !authenticated || instrument != Instrument.EURUSD || !Period.ONE_HOUR.equals(period)) return;
        if (ask == null || bid == null || ask.getTime() != bid.getTime()) {
            spool.event("gap", 0);
            return;
        }
        spool.event("h1", bid.getTime(), bid.getOpen(), bid.getHigh(), bid.getLow(), bid.getClose(),
                    ask.getOpen(), ask.getHigh(), ask.getLow(), ask.getClose());
    }

    private static boolean awaitConnection(IClient client, Spool spool) throws Exception {
        for (int i = 0; i < 30; i++) {
            spool.check();
            if (client.isConnected()) return true;
            Thread.sleep(1000);
        }
        return false;
    }

    private static void run(Path file, int seconds, boolean includeWarmup, String login, char[] password) throws Exception {
        try (Spool spool = new Spool(file, false, 8192)) {
            IClient client = ClientFactory.getDefaultInstance();
            DemoCollector strategy = new DemoCollector(spool, includeWarmup
                    ? file.resolveSibling(file.getFileName() + ".warmup.csv") : null);
            client.setSystemListener(new ISystemListener() {
                @Override public void onStart(long id) {}
                @Override public void onStop(long id) {}
                @Override public void onConnect() { spool.event("connected", 0); }
                @Override public void onDisconnect() {
                    strategy.active = false;
                    strategy.authenticated = false;
                    spool.event("disconnected", 0);
                }
            });
            try {
                try {
                    spool.event("connecting", 0);
                    client.connect(DEMO, login, new String(password));
                } finally { Arrays.fill(password, '\0'); }
                if (!awaitConnection(client, spool)) throw new IllegalStateException("initial connection unavailable");
                long id = -1;
                long deadline = System.nanoTime() + seconds * 1_000_000_000L;
                int retries = 0;
                while (System.nanoTime() < deadline) {
                    spool.check();
                    if (!client.isConnected() || !strategy.active) {
                        if (!client.isConnected()) {
                            if (retries >= 3 || !client.isReconnectAllowed())
                                throw new IllegalStateException("reconnect unavailable");
                            Thread.sleep(5000L << retries++);
                            spool.event("reconnecting", 0);
                            client.reconnect();
                            if (!awaitConnection(client, spool)) continue;
                        }
                        client.setSubscribedInstruments(Set.of(Instrument.EURUSD));
                        if (!client.getSubscribedInstruments().contains(Instrument.EURUSD))
                            throw new IllegalStateException("EURUSD subscription not reported");
                        if (id < 0 || !client.getStartedStrategies().containsKey(id))
                            id = client.startStrategy(strategy);
                        spool.event("subscribed", 0);
                        strategy.active = true;
                    }
                    if (!client.getStartedStrategies().containsKey(id))
                        throw new IllegalStateException("strategy unavailable");
                    spool.event("heartbeat", 0);
                    Thread.sleep(5000);
                }
            } catch (Exception failure) {
                spool.event("collector_fault", 0);
                throw failure;
            } finally {
                strategy.active = false;
                client.disconnect();
            }
        }
    }

    public static void main(String[] args) {
        PrintStream operator = System.err;
        if (args.length < 2 || args.length > 3 || (args.length == 3 && !"--no-warmup".equals(args[2]))) {
            System.err.println("DemoCollector PRIVATE_NEW_TSV SECONDS [--no-warmup]");
            System.exit(2);
        }
        char[] password = null;
        try {
            int seconds = Integer.parseInt(args[1]);
            if (seconds < 1 || seconds > 7 * 24 * 3600) throw new IllegalArgumentException();
            Console console = System.console();
            char[] loginChars;
            if (console != null) {
                loginChars = console.readPassword("Authorized JForex DEMO login (hidden): ");
                password = console.readPassword("DEMO password: ");
            } else {
                JPanel fields = new JPanel(new GridLayout(0, 1));
                JPasswordField loginField = new JPasswordField(24), passField = new JPasswordField(24);
                fields.add(new JLabel("Dukascopy DEMO username (hidden)")); fields.add(loginField);
                fields.add(new JLabel("Dukascopy DEMO password (hidden)")); fields.add(passField);
                int choice = JOptionPane.showConfirmDialog(null, fields, "Emtifize JForex DEMO credential entry",
                        JOptionPane.OK_CANCEL_OPTION, JOptionPane.PLAIN_MESSAGE);
                loginChars = choice == JOptionPane.OK_OPTION ? loginField.getPassword() : null;
                password = choice == JOptionPane.OK_OPTION ? passField.getPassword() : null;
                loginField.setText("");
                passField.setText("");
            }
            if (loginChars == null) throw new IllegalArgumentException();
            String login = new String(loginChars);
            Arrays.fill(loginChars, '\0');
            if (login == null || login.isBlank() || password == null || password.length == 0)
                throw new IllegalArgumentException();
            // The spool is the only diagnostic output during vendor authentication.
            System.setProperty("log4j.defaultInitOverride", "true");
            System.setOut(new PrintStream(OutputStream.nullOutputStream()));
            System.setErr(new PrintStream(OutputStream.nullOutputStream()));
            operator.println("Connecting to Dukascopy DEMO. Credentials are hidden.");
            run(Path.of(args[0]), seconds, args.length == 2, login, password);
            operator.println("Diagnostic capture closed.");
        } catch (Exception e) {
            // Vendor exception messages can contain account information.
            operator.println("DEMO collector stopped: " + e.getClass().getSimpleName());
            System.exit(1);
        } finally { if (password != null) Arrays.fill(password, '\0'); }
    }
}
