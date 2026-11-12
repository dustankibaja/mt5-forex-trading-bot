package ai.emtifize;

import java.nio.file.Path;

/** Exercises the same spool without loading or authenticating the SDK. */
public final class Fixture {
    public static void main(String[] args) throws Exception {
        try (Spool spool = new Spool(Path.of(args[0]), true, 256)) {
            spool.event("connected", 0);
            spool.event("subscribed", 0);
            long now = System.currentTimeMillis();
            spool.event("tick", now - 40, 1.1000, 1.1002);
            spool.event("tick", now - 40, 1.1000, 1.1002);
            spool.event("tick", now - 3000, 1.1001, 1.1003);
            spool.event("disconnected", 0);
            spool.event("connected", 0);
            spool.event("subscribed", 0);
            spool.event("tick", System.currentTimeMillis(), 1.1002, 1.1004);
            long hour = Math.floorDiv(now, 3_600_000) * 3_600_000 - 3_600_000;
            spool.event("h1", hour, 1.1000, 1.1010, 1.0990, 1.1005,
                                    1.1002, 1.1012, 1.0992, 1.1007);
        }
    }
}
