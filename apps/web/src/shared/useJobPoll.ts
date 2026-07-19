import { useCallback, useRef } from "react";
import { api, type JobRecord } from "../api/client";

export type JobPollOptions = {
  intervalMs?: number;
  timeoutMs?: number;
  onUpdate?: (job: JobRecord) => void;
};

/** 轮询 job 直至 succeeded / failed / 超时。 */
export async function pollJob(
  jobId: string,
  opts: JobPollOptions = {},
): Promise<JobRecord> {
  const interval = opts.intervalMs ?? 600;
  const timeout = opts.timeoutMs ?? 120_000;
  const start = Date.now();
  for (;;) {
    const job = await api.job(jobId);
    opts.onUpdate?.(job);
    if (job.status === "succeeded" || job.status === "failed") return job;
    if (Date.now() - start > timeout) {
      throw new Error(`任务超时: ${jobId}`);
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

export function useJobRunner() {
  const abortRef = useRef(false);

  const run = useCallback(async (jobId: string, opts?: JobPollOptions) => {
    abortRef.current = false;
    return pollJob(jobId, {
      ...opts,
      onUpdate: (j) => {
        if (!abortRef.current) opts?.onUpdate?.(j);
      },
    });
  }, []);

  const cancel = useCallback(() => {
    abortRef.current = true;
  }, []);

  return { run, cancel };
}
