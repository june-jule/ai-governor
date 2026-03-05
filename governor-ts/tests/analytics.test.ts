import { describe, it, expect } from "vitest";
import { GovernorAnalytics } from "../src/analytics/graph_algorithms.js";

describe("GovernorAnalytics", () => {
  it("can be imported", () => {
    expect(GovernorAnalytics).toBeDefined();
  });

  it("GDS stubs throw informative errors", async () => {
    // Create a minimal mock backend (analytics constructor just stores it)
    const mockBackend = {} as ConstructorParameters<typeof GovernorAnalytics>[0];
    const analytics = new GovernorAnalytics(mockBackend);

    await expect(analytics.getTaskCriticality()).rejects.toThrow("GDS plugin");
    await expect(analytics.getBlockingBottlenecks()).rejects.toThrow("GDS plugin");
    await expect(analytics.detectCircularDependencies()).rejects.toThrow("GDS plugin");
    await expect(analytics.getTaskClusters()).rejects.toThrow("GDS plugin");
  });
});
