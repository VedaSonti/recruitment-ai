"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { runMatchingAnalysis, type Job } from "@/src/lib/api";
import { getJobId, getJobTitle } from "@/src/lib/utils";

const SELECTED_JOB_STORAGE_KEY = "recruitment-ai:selected-matching-job";

export function MatchingAction({
  candidateCount,
  isLoading,
  jobs,
  processedCount = 0,
}: {
  candidateCount: number;
  isLoading: boolean;
  jobs: Job[];
  processedCount?: number;
}) {
  const router = useRouter();
  const [selectedJobId, setSelectedJobId] = useState("");
  const [isMatching, setIsMatching] = useState(false);
  const [matchingError, setMatchingError] = useState("");

  const logMatching = useCallback((message: string, value?: unknown) => {
    if (process.env.NODE_ENV !== "production") {
      if (value === undefined) {
        console.info(message);
      } else {
        console.info(message, value);
      }
    }
  }, []);

  useEffect(() => {
    const availableJobIds = jobs.map(getJobId).filter(Boolean);
    setSelectedJobId((current) => {
      if (current && availableJobIds.includes(current)) {
        return current;
      }

      let storedJobId = "";
      try {
        storedJobId = window.sessionStorage.getItem(SELECTED_JOB_STORAGE_KEY) ?? "";
      } catch {
        // Session storage can be unavailable in privacy-restricted browsers.
      }
      if (storedJobId && availableJobIds.includes(storedJobId)) {
        return storedJobId;
      }

      return availableJobIds.length === 1 ? availableJobIds[0] : "";
    });
  }, [jobs]);

  const selectJob = useCallback((jobId: string) => {
    setSelectedJobId(jobId);
    try {
      if (jobId) {
        window.sessionStorage.setItem(SELECTED_JOB_STORAGE_KEY, jobId);
      } else {
        window.sessionStorage.removeItem(SELECTED_JOB_STORAGE_KEY);
      }
    } catch {
      // The visible selection remains usable even without session storage.
    }
  }, []);

  const handleRunMatching = useCallback(async () => {
    logMatching("[matching-ui] button clicked");
    logMatching("[matching-ui] selectedJobId=", selectedJobId);
    logMatching("[matching-ui] candidatesLoaded=", candidateCount);
    setMatchingError("");

    const selectedJobExists = jobs.some((job) => getJobId(job) === selectedJobId);
    if (!selectedJobId || !selectedJobExists || candidateCount < 1) {
      const error = "Select a valid job and upload at least one CV before matching.";
      logMatching("[matching-ui] request failed", error);
      setMatchingError(error);
      return;
    }

    setIsMatching(true);
    try {
      logMatching("[matching-ui] calling runMatchingAnalysis");
      await runMatchingAnalysis(selectedJobId);
      logMatching("[matching-ui] request completed");
      router.push(`/matches/${encodeURIComponent(selectedJobId)}`);
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Matching analysis could not be started.";
      logMatching("[matching-ui] request failed", message);
      setMatchingError(message);
    } finally {
      setIsMatching(false);
    }
  }, [candidateCount, jobs, logMatching, router, selectedJobId]);

  if (isLoading) {
    return null;
  }

  if (jobs.length === 0) {
    return (
      <p className="text-[14px] font-semibold text-slate-500">
        Upload a Job Description to run matching.
      </p>
    );
  }

  if (candidateCount === 0) {
    return (
      <p className="text-[14px] font-semibold text-slate-500">
        Upload at least one CV to run matching.
      </p>
    );
  }

  const displayedCount = processedCount > 0 ? processedCount : candidateCount;

  return (
    <section className="flex flex-col gap-4 rounded-2xl bg-brand px-6 py-5 text-white shadow-lg shadow-brand/15 md:flex-row md:items-center md:justify-between">
      <p className="text-[16px] font-bold">
        {"\u2713"} {displayedCount} CV{displayedCount === 1 ? "" : "s"} available for matching
      </p>
      <div className="min-w-[240px]">
        {jobs.length > 1 ? (
          <label className="mb-3 block">
            <span className="mb-1.5 block text-[12px] font-bold text-white/90">
              Match against job
            </span>
            <select
              className="field h-10 bg-white text-slate-900"
              onChange={(event) => selectJob(event.target.value)}
              value={selectedJobId}
            >
              <option value="">Select a job</option>
              {jobs.map((job) => {
                const jobId = getJobId(job);
                return jobId ? (
                  <option key={jobId} value={jobId}>
                    {getJobTitle(job)}
                  </option>
                ) : null;
              })}
            </select>
          </label>
        ) : null}
        <Button
          className="w-full bg-white text-crimson-700 hover:bg-[#f8f8f8]"
          disabled={!selectedJobId}
          isLoading={isMatching}
          onClick={handleRunMatching}
          type="button"
          variant="secondary"
        >
          Run Matching Analysis
        </Button>
        {matchingError ? (
          <p className="mt-2 text-[13px] font-semibold text-white" role="alert">
            {matchingError}
          </p>
        ) : null}
      </div>
    </section>
  );
}
