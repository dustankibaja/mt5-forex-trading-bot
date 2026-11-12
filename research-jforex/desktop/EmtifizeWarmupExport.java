package jforex;

import com.dukascopy.api.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Collections;
import java.util.List;
import java.util.UUID;

/** One-shot history export on an already subscribed Desktop DEMO session. */
@RequiresFullAccess
public final class EmtifizeWarmupExport implements IStrategy {
    private IContext context;
    private boolean attempted;

    @Override public void onStart(IContext context) throws JFException {
        if (context.getEngine().getType() != IEngine.Type.DEMO) {
            context.stop();
            return;
        }
        this.context = context;
        context.setSubscribedInstruments(Collections.singleton(Instrument.EURUSD), true);
    }

    @Override public void onTick(Instrument instrument, ITick tick) {
        if (instrument != Instrument.EURUSD || attempted) return;
        attempted = true;
        String stage = "bid history";
        try {
            IHistory history = context.getHistory();
            long tickTime = tick.getTime();
            long cutoff = history.getPreviousBarStart(Period.ONE_HOUR, tickTime);
            List<IBar> bids = history.getBars(Instrument.EURUSD, Period.ONE_HOUR, OfferSide.BID,
                                            Filter.NO_FILTER, 220, cutoff, 0);
            stage = "ask history";
            List<IBar> asks = history.getBars(Instrument.EURUSD, Period.ONE_HOUR, OfferSide.ASK,
                                            Filter.NO_FILTER, 220, cutoff, 0);
            stage = "pair validation and export";
            if (bids.size() != asks.size() || bids.size() < 211)
                throw new IOException("Insufficient paired bars");
            StringBuilder csv = new StringBuilder(
                    "provenance,raw_open_ms,bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c\n");
            long previous = 0;
            for (int i = 0; i < bids.size(); i++) {
                IBar bid = bids.get(i), ask = asks.get(i);
                long open = bid.getTime();
                if (open != ask.getTime() || open <= previous || open % 3_600_000L != 0
                        || open + 3_600_000L > tickTime)
                    throw new IOException("Invalid paired bar timestamps");
                if (ask.getClose() < bid.getClose()) throw new IOException("Crossed closing prices");
                csv.append("jforex_live_origin_warmup,").append(open);
                appendPrices(csv, bid);
                appendPrices(csv, ask);
                csv.append('\n');
                previous = open;
            }
            if (previous != cutoff) throw new IOException("Missing most recent completed pair");
            Path directory = Paths.get(System.getenv("LOCALAPPDATA"), "EmtifizeResearch", "JForex");
            Path target = directory.resolve("warmup-desktop-" + UUID.randomUUID() + ".csv");
            Files.write(target, csv.toString().getBytes(StandardCharsets.US_ASCII),
                        StandardOpenOption.CREATE_NEW);
            context.getConsole().getOut().println("Completed historical EUR/USD pairs exported: " + bids.size());
        } catch (Exception failure) {
            context.getConsole().getErr().println("Warm-up export failed during " + stage + ": " + failure.getClass().getSimpleName());
        } finally {
            context.stop();
        }
    }

    private static void appendPrices(StringBuilder csv, IBar bar) throws IOException {
        double open = bar.getOpen(), high = bar.getHigh(), low = bar.getLow(), close = bar.getClose();
        if (!Double.isFinite(open) || !Double.isFinite(high) || !Double.isFinite(low)
                || !Double.isFinite(close) || low <= 0 || low > Math.min(open, close)
                || high < Math.max(open, close))
            throw new IOException("Invalid bar geometry");
        csv.append(',').append(open).append(',').append(high).append(',').append(low).append(',').append(close);
    }


    @Override public void onBar(Instrument instrument, Period period, IBar ask, IBar bid) {}
    @Override public void onMessage(IMessage message) {}
    @Override public void onAccount(IAccount account) {}
    @Override public void onStop() {}
}
