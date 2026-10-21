/**
 * Share one in-flight promise between concurrent callers.
 *
 * Used for token refresh: a rotated refresh token is single-use, so parallel
 * 401s must await the same request instead of racing each other.
 */
export function createSingleFlight<T>(task: () => Promise<T>): () => Promise<T> {
    let inFlight: Promise<T> | null = null;
    return () => {
        if (!inFlight) {
            inFlight = task().finally(() => {
                inFlight = null;
            });
        }
        return inFlight;
    };
}
