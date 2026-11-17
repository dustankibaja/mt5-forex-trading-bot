package jforex;

import com.dukascopy.api.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;

/** Progressive, one-shot history export on an authenticated Desktop DEMO session. */
@RequiresFullAccess
public final class EmtifizeWarmupExport implements IStrategy {
    private IContext context;
    private boolean attempted;
    private int asyncStage;
    private long asyncCurrentStart;
    private List<LoadedBar> asyncBids;
    private static final int[] ASYNC_HOURS = {1, 5, 24, 336};
    private static final int[] ASYNC_MINIMUM_PAIRS = {1, 5, 24, 211};

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
        String operation = "initialization";
        long from = 0, to = 0, currentStart = 0;
        try {
            IHistory history = context.getHistory();
            currentStart = history.getBarStart(Period.ONE_HOUR, tick.getTime());

            operation = "getBar BID shift=1";
            IBar latestBid = requireBar(history.getBar(Instrument.EURUSD, Period.ONE_HOUR,
                                                       OfferSide.BID, 1), operation);
            operation = "getBar ASK shift=1";
            IBar latestAsk = requireBar(history.getBar(Instrument.EURUSD, Period.ONE_HOUR,
                                                       OfferSide.ASK, 1), operation);
            validatePair(latestBid, latestAsk, currentStart);
            logSuccess("latest completed pair", 1, latestBid.getTime(), latestBid.getTime());

            operation = "getBar BID/ASK shifts=1..5";
            List<IBar> fiveBids = new ArrayList<>();
            List<IBar> fiveAsks = new ArrayList<>();
            for (int shift = 5; shift >= 1; shift--) {
                fiveBids.add(requireBar(history.getBar(Instrument.EURUSD, Period.ONE_HOUR,
                                                       OfferSide.BID, shift), operation));
                fiveAsks.add(requireBar(history.getBar(Instrument.EURUSD, Period.ONE_HOUR,
                                                       OfferSide.ASK, shift), operation));
            }
            validatePairs(fiveBids, fiveAsks, currentStart, 5);
            logSuccess("five completed pairs", 5, fiveBids.get(0).getTime(), latestBid.getTime());

            operation = "getBars exact recent 5-hour interval";
            from = fiveBids.get(0).getTime();
            to = latestBid.getTime();
            List<IBar> exactBids = history.getBars(Instrument.EURUSD, Period.ONE_HOUR,
                                                   OfferSide.BID, Filter.NO_FILTER, from, to);
            List<IBar> exactAsks = history.getBars(Instrument.EURUSD, Period.ONE_HOUR,
                                                   OfferSide.ASK, Filter.NO_FILTER, from, to);
            validatePairs(exactBids, exactAsks, currentStart, 5);
            logSuccess("exact recent interval", exactBids.size(), from, to);

            operation = "getBars 24 completed pairs";
            from = history.getTimeForNBarsBack(Period.ONE_HOUR, latestBid.getTime(), 24);
            List<IBar> dayBids = history.getBars(Instrument.EURUSD, Period.ONE_HOUR,
                                                OfferSide.BID, Filter.WEEKENDS, 24, latestBid.getTime(), 0);
            List<IBar> dayAsks = history.getBars(Instrument.EURUSD, Period.ONE_HOUR,
                                                OfferSide.ASK, Filter.WEEKENDS, 24, latestBid.getTime(), 0);
            validatePairs(dayBids, dayAsks, currentStart, 24);
            logSuccess("24 completed pairs", dayBids.size(), dayBids.get(0).getTime(), currentStart);

            operation = "getBars 220 completed pairs";
            from = history.getTimeForNBarsBack(Period.ONE_HOUR, latestBid.getTime(), 220);
            List<IBar> bids = history.getBars(Instrument.EURUSD, Period.ONE_HOUR,
                                              OfferSide.BID, Filter.WEEKENDS, 220, latestBid.getTime(), 0);
            List<IBar> asks = history.getBars(Instrument.EURUSD, Period.ONE_HOUR,
                                              OfferSide.ASK, Filter.WEEKENDS, 220, latestBid.getTime(), 0);
            validatePairs(bids, asks, currentStart, 211);
            export(bids, asks);
            logSuccess("warm-up export", bids.size(), bids.get(0).getTime(), currentStart);
            context.stop();
        } catch (Exception failure) {
            String diagnostic = sanitizedFailure(operation, from, to, failure);
            recordDiagnostic(diagnostic);
            context.getConsole().getErr().println(diagnostic);
            if (operation.startsWith("getBar") && startAsyncProbe(currentStart)) return;
            context.stop();
        }
    }

    private boolean startAsyncProbe(long currentStart) {
        asyncCurrentStart = currentStart;
        asyncStage = 0;
        return readAsyncSide(OfferSide.BID);
    }

    private boolean readAsyncSide(OfferSide side) {
        String operation = "readBars asynchronous " + side + " stage=" + asyncStage;
        long from = asyncCurrentStart - ASYNC_HOURS[asyncStage] * 3_600_000L;
        long to = asyncCurrentStart;
        List<LoadedBar> loaded = new ArrayList<>();
        try {
            context.getHistory().readBars(
                    Instrument.EURUSD, Period.ONE_HOUR, side, Filter.WEEKENDS, from, to,
                    new LoadingDataListener() {
                        @Override public void newTick(Instrument instrument, long time, double ask,
                                                      double bid, double askVolume, double bidVolume) {}
                        @Override public void newBar(Instrument instrument, Period period,
                                                     OfferSide side, long time, double open,
                                                     double close, double low, double high,
                                                     double volume) {
                            loaded.add(new LoadedBar(time, open, high, low, close));
                        }
                    },
                    new LoadingProgressListener() {
                        @Override public void dataLoaded(long startTime, long endTime,
                                                        long currentTime, String information) {}
                        @Override public void loadingFinished(boolean allDataLoaded, long startTime,
                                                              long endTime, long currentTime) {
                            finishAsyncSide(side, loaded, allDataLoaded, from, to);
                        }
                        @Override public boolean stopJob() { return false; }
                    });
            return true;
        } catch (Exception failure) {
            String diagnostic = sanitizedFailure(operation, from, to, failure);
            recordDiagnostic(diagnostic);
            context.getConsole().getErr().println(diagnostic);
            return false;
        }
    }

    private void finishAsyncSide(OfferSide side, List<LoadedBar> loaded,
                                 boolean allDataLoaded, long from, long to) {
        loaded.sort(Comparator.comparingLong(bar -> bar.time));
        String result = "Warm-up asynchronous stage: side=" + side + "; stage=" + asyncStage
                + "; allDataLoaded=" + allDataLoaded + "; bars=" + loaded.size()
                + "; interval=" + interval(from, to);
        recordDiagnostic(result);
        context.getConsole().getOut().println(result);
        if (!allDataLoaded) {
            context.stop();
            return;
        }
        if (side == OfferSide.BID) {
            asyncBids = loaded;
            if (!readAsyncSide(OfferSide.ASK)) context.stop();
            return;
        }
        try {
            validateLoadedPairs(asyncBids, loaded, asyncCurrentStart,
                                ASYNC_MINIMUM_PAIRS[asyncStage]);
            String paired = "Warm-up asynchronous pairs passed: stage=" + asyncStage
                    + "; pairs=" + loaded.size() + "; minimum="
                    + ASYNC_MINIMUM_PAIRS[asyncStage];
            recordDiagnostic(paired);
            context.getConsole().getOut().println(paired);
            if (asyncStage == ASYNC_HOURS.length - 1) {
                exportLoaded(asyncBids, loaded);
                String exported = "Warm-up asynchronous export written: pairs="
                        + Math.min(220, loaded.size());
                recordDiagnostic(exported);
                context.getConsole().getOut().println(exported);
                context.stop();
                return;
            }
            asyncStage++;
            if (!readAsyncSide(OfferSide.BID)) context.stop();
        } catch (Exception failure) {
            String diagnostic = sanitizedFailure("validate asynchronous pairs stage=" + asyncStage,
                                                 from, to, failure);
            recordDiagnostic(diagnostic);
            context.getConsole().getErr().println(diagnostic);
            context.stop();
        }
    }

    private void exportLoaded(List<LoadedBar> bids, List<LoadedBar> asks) throws IOException {
        int first = Math.max(0, bids.size() - 220);
        StringBuilder csv = new StringBuilder(
                "provenance,raw_open_ms,bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c\n");
        for (int i = first; i < bids.size(); i++) {
            csv.append("jforex_live_origin_warmup,").append(bids.get(i).time);
            appendLoadedPrices(csv, bids.get(i));
            appendLoadedPrices(csv, asks.get(i));
            csv.append('\n');
        }
        Path directory = Paths.get(System.getenv("LOCALAPPDATA"), "EmtifizeResearch", "JForex");
        Path target = directory.resolve("warmup-desktop-" + UUID.randomUUID() + ".csv");
        Files.write(target, csv.toString().getBytes(StandardCharsets.US_ASCII),
                    StandardOpenOption.CREATE_NEW);
    }

    private static void validateLoadedPairs(List<LoadedBar> bids, List<LoadedBar> asks,
                                            long currentStart, int minimum) throws IOException {
        if (bids == null || asks == null || bids.size() != asks.size() || bids.size() < minimum)
            throw new IOException("Insufficient asynchronous paired bars");
        long previous = 0;
        for (int i = 0; i < bids.size(); i++) {
            LoadedBar bid = bids.get(i), ask = asks.get(i);
            if (bid.time != ask.time || bid.time <= previous || bid.time % 3_600_000L != 0
                    || bid.time >= currentStart)
                throw new IOException("Invalid asynchronous pair timestamp");
            validateLoadedGeometry(bid);
            validateLoadedGeometry(ask);
            if (ask.close < bid.close) throw new IOException("Crossed asynchronous closing prices");
            previous = bid.time;
        }
    }

    private static void validateLoadedGeometry(LoadedBar bar) throws IOException {
        if (!Double.isFinite(bar.open) || !Double.isFinite(bar.high)
                || !Double.isFinite(bar.low) || !Double.isFinite(bar.close)
                || bar.low <= 0 || bar.low > Math.min(bar.open, bar.close)
                || bar.high < Math.max(bar.open, bar.close))
            throw new IOException("Invalid asynchronous OHLC geometry");
    }

    private static void appendLoadedPrices(StringBuilder csv, LoadedBar bar) {
        csv.append(',').append(bar.open).append(',').append(bar.high)
           .append(',').append(bar.low).append(',').append(bar.close);
    }

    private static final class LoadedBar {
        final long time;
        final double open, high, low, close;

        LoadedBar(long time, double open, double high, double low, double close) {
            this.time = time;
            this.open = open;
            this.high = high;
            this.low = low;
            this.close = close;
        }
    }

    private void export(List<IBar> bids, List<IBar> asks) throws IOException {
        StringBuilder csv = new StringBuilder(
                "provenance,raw_open_ms,bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c\n");
        for (int i = 0; i < bids.size(); i++) {
            csv.append("jforex_live_origin_warmup,").append(bids.get(i).getTime());
            appendPrices(csv, bids.get(i));
            appendPrices(csv, asks.get(i));
            csv.append('\n');
        }
        Path directory = Paths.get(System.getenv("LOCALAPPDATA"), "EmtifizeResearch", "JForex");
        Path target = directory.resolve("warmup-desktop-" + UUID.randomUUID() + ".csv");
        Files.write(target, csv.toString().getBytes(StandardCharsets.US_ASCII),
                    StandardOpenOption.CREATE_NEW);
    }

    private static IBar requireBar(IBar bar, String operation) throws IOException {
        if (bar == null) throw new IOException(operation + " returned no cached candle");
        return bar;
    }

    private static void validatePairs(List<IBar> bids, List<IBar> asks,
                                      long currentStart, int minimum) throws IOException {
        if (bids == null || asks == null || bids.size() != asks.size() || bids.size() < minimum)
            throw new IOException("Insufficient paired bars");
        long previous = 0;
        for (int i = 0; i < bids.size(); i++) {
            validatePair(bids.get(i), asks.get(i), currentStart);
            long opening = bids.get(i).getTime();
            if (opening <= previous) throw new IOException("Bars are not chronological");
            previous = opening;
        }
    }

    private static void validatePair(IBar bid, IBar ask, long currentStart) throws IOException {
        if (bid == null || ask == null || bid.getTime() != ask.getTime()
                || bid.getTime() % 3_600_000L != 0 || bid.getTime() >= currentStart)
            throw new IOException("Invalid completed pair timestamp");
        validateGeometry(bid);
        validateGeometry(ask);
        if (ask.getClose() < bid.getClose()) throw new IOException("Crossed closing prices");
    }

    private static void validateGeometry(IBar bar) throws IOException {
        double open = bar.getOpen(), high = bar.getHigh(), low = bar.getLow(), close = bar.getClose();
        if (!Double.isFinite(open) || !Double.isFinite(high) || !Double.isFinite(low)
                || !Double.isFinite(close) || low <= 0 || low > Math.min(open, close)
                || high < Math.max(open, close))
            throw new IOException("Invalid OHLC geometry");
    }

    private static void appendPrices(StringBuilder csv, IBar bar) {
        csv.append(',').append(bar.getOpen()).append(',').append(bar.getHigh())
           .append(',').append(bar.getLow()).append(',').append(bar.getClose());
    }

    private void logSuccess(String operation, int count, long from, long to) {
        context.getConsole().getOut().println("Warm-up stage passed: " + operation
                + "; pairs=" + count + "; interval=" + interval(from, to));
    }

    private static String sanitizedFailure(String operation, long from, long to, Throwable failure) {
        StringBuilder out = new StringBuilder("Warm-up stage failed: operation=").append(operation)
                .append("; interval=").append(interval(from, to));
        Throwable cursor = failure;
        for (int depth = 0; cursor != null && depth < 3; depth++, cursor = cursor.getCause()) {
            out.append("; ").append(depth == 0 ? "exception=" : "cause=")
               .append(cursor.getClass().getSimpleName());
            String message = cursor.getMessage();
            if (message != null && !message.trim().isEmpty())
                out.append('(').append(sanitize(message)).append(')');
        }
        return out.toString();
    }

    private static String sanitize(String message) {
        String clean = message.replaceAll("[\\r\\n\\t]+", " ").trim();
        clean = clean.replaceAll("(?i)(login|account|password|token|user(name)?)\\s*[=:]\\s*[^ ,;]+",
                                 "$1=[redacted]");
        return clean.length() > 240 ? clean.substring(0, 240) : clean;
    }

    private static String interval(long from, long to) {
        if (from <= 0 && to <= 0) return "unset";
        return (from <= 0 ? "unset" : Instant.ofEpochMilli(from).toString()) + ".."
                + (to <= 0 ? "unset" : Instant.ofEpochMilli(to).toString());
    }

    private static void recordDiagnostic(String line) {
        try {
            Path directory = Paths.get(System.getenv("LOCALAPPDATA"), "EmtifizeResearch", "JForex");
            Path target = directory.resolve("warmup-diagnostic-" + UUID.randomUUID() + ".txt");
            Files.write(target, (line + "\n").getBytes(StandardCharsets.UTF_8),
                        StandardOpenOption.CREATE_NEW);
        } catch (IOException ignored) {
            // Console output remains available when the private diagnostic cannot be written.
        }
    }

    @Override public void onBar(Instrument instrument, Period period, IBar ask, IBar bid) {}
    @Override public void onMessage(IMessage message) {}
    @Override public void onAccount(IAccount account) {}
    @Override public void onStop() {}
}
