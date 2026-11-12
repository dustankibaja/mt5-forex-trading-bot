package ai.emtifize;

import com.dukascopy.api.*;
import com.dukascopy.api.system.*;
import java.io.Console;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Set;

/** A fixed DEMO endpoint and one instrument. No order or account-state handling. */
public final class DemoCollector implements IStrategy {
    private static final String DEMO = "https://platform.dukascopy.com/demo_3/jforex_3.jnlp";
    private final Spool spool;
    private volatile boolean active;

    DemoCollector(Spool spool) { this.spool = spool; }
    @Override public void onStart(IContext ignored) { spool.event("strategy_started", 0); }
    @Override public void onStop() { spool.event("strategy_stopped", 0); }
    @Override public void onMessage(IMessage ignored) {}
    @Override public void onAccount(IAccount ignored) {}
    @Override public void onTick(Instrument instrument, ITick tick) {
        if (active && instrument == Instrument.EURUSD)
            spool.event("tick", tick.getTime(), tick.getBid(), tick.getAsk());
    }
    @Override public void onBar(Instrument instrument, Period period, IBar ask, IBar bid) {
        if (!active || instrument != Instrument.EURUSD || !Period.ONE_HOUR.equals(period)) return;
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

    private static void run(Path file, int seconds, String login, char[] password) throws Exception {
        try (Spool spool = new Spool(file, false, 8192)) {
            IClient client = ClientFactory.getDefaultInstance();
            DemoCollector strategy = new DemoCollector(spool);
            client.setSystemListener(new ISystemListener() {
                @Override public void onStart(long id) {}
                @Override public void onStop(long id) {}
                @Override public void onConnect() { spool.event("connected", 0); }
                @Override public void onDisconnect() {
                    strategy.active = false;
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
        if (args.length != 2 || System.console() == null) {
            System.err.println("Run from an interactive console: DemoCollector PRIVATE_NEW_TSV SECONDS");
            System.exit(2);
        }
        char[] password = null;
        try {
            int seconds = Integer.parseInt(args[1]);
            if (seconds < 1 || seconds > 7 * 24 * 3600) throw new IllegalArgumentException();
            Console console = System.console();
            String login = console.readLine("Authorized JForex DEMO login: ");
            password = console.readPassword("DEMO password: ");
            if (login == null || login.isBlank() || password == null || password.length == 0)
                throw new IllegalArgumentException();
            run(Path.of(args[0]), seconds, login, password);
        } catch (Exception e) {
            // Vendor exception messages can contain account information.
            System.err.println("DEMO collector stopped: " + e.getClass().getSimpleName());
            System.exit(1);
        } finally { if (password != null) Arrays.fill(password, '\0'); }
    }
}
