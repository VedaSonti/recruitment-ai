"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, FileText } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { UploadWorkflow } from "@/components/upload/UploadWorkflow";
import {
  getCandidates,
  getJobs,
  runMatchingAnalysis,
  uploadCandidate,
  type Candidate,
} from "@/src/lib/api";
import { formatDate, getCandidateId, getJobId } from "@/src/lib/utils";

export default function UploadCvsPage() {
  const router = useRouter();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [mostRecentJobId, setMostRecentJobId] = useState("");
  const [processedCount, setProcessedCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
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

  const loadData = useCallback(async () => {
    setIsLoading(true);
    const [candidateList, jobs] = await Promise.all([getCandidates(), getJobs()]);
    setCandidates(candidateList);
    setMostRecentJobId(getJobId(jobs[0] ?? {}));
    setIsLoading(false);
  }, []);

  useEffect(() => {
    loadData().catch(() => setIsLoading(false));
  }, [loadData]);

  const handleProcessed = useCallback(
    (count: number) => {
      setProcessedCount(count);
      loadData().catch(() => undefined);
    },
    [loadData],
  );

  const handleRunMatching = useCallback(async () => {
    logMatching("[matching-ui] button clicked");
    logMatching("[matching-ui] selectedJobId=", mostRecentJobId);
    logMatching("[matching-ui] candidatesLoaded=", candidates.length);
    setMatchingError("");

    if (!mostRecentJobId) {
      const error = "No job is available for matching.";
      logMatching("[matching-ui] request failed", error);
      setMatchingError(error);
      return;
    }

    setIsMatching(true);
    try {
      logMatching("[matching-ui] calling runMatchingAnalysis");
      await runMatchingAnalysis(mostRecentJobId);
      logMatching("[matching-ui] request completed");
      router.push(`/matches/${encodeURIComponent(mostRecentJobId)}`);
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
  }, [candidates.length, logMatching, mostRecentJobId, router]);

  return (
    <>
      <PageHeader
        subtitle="Upload multiple candidate CVs for batch processing and matching"
        title="Upload Candidate CVs"
      />

      <div className="grid items-start gap-8 xl:grid-cols-[2fr_0.95fr]">
        <div className="space-y-7">
          <UploadWorkflow
            dropTitle="Drop candidate CVs here"
            helperText="or click to browse and select multiple files. Supports PDF, DOCX - Bulk upload supported"
            onClear={() => setProcessedCount(0)}
            onProcessed={handleProcessed}
            upload={uploadCandidate}
          />

          {processedCount > 0 ? (
            <section className="flex flex-col gap-4 rounded-2xl bg-brand px-6 py-5 text-white shadow-lg shadow-brand/15 md:flex-row md:items-center md:justify-between">
              <p className="text-[16px] font-bold">
                {"\u2713"} {processedCount} CV{processedCount === 1 ? "" : "s"} uploaded - match against all existing jobs?
              </p>
              {mostRecentJobId ? (
                <div>
                  <Button
                    className="bg-white text-crimson-700 hover:bg-[#f8f8f8]"
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
              ) : (
                <p className="text-[14px] font-bold text-white/90">
                  Upload job descriptions first before running matching
                </p>
              )}
            </section>
          ) : null}
        </div>

        <Card className="self-start px-6 py-6">
          <CardHeader className="mb-5" title="Uploaded Candidates" />
          {isLoading ? (
            <div className="flex justify-center py-10">
              <LoadingSpinner />
            </div>
          ) : (
            <div className="space-y-4">
              {candidates.slice(0, 6).map((candidate) => (
                <RecentCandidateCard
                  candidate={candidate}
                  key={getCandidateId(candidate) || candidate.name}
                />
              ))}
              {candidates.length === 0 ? (
                <p className="py-6 text-center text-[14px] text-[#77777a]">
                  No candidates uploaded yet.
                </p>
              ) : null}
            </div>
          )}
        </Card>
      </div>

      <section className="mt-8">
        <h2 className="mb-4 font-display text-[20px] font-bold text-slate-900">
          Uploaded Candidates
        </h2>
        <Card className="overflow-hidden">
          {isLoading ? (
            <div className="flex justify-center py-12">
              <LoadingSpinner />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse text-left">
                <thead className="table-head">
                  <tr>
                    {["Name", "Email", "Skills", "Work Rights", "Notice Period", "View Profile"].map((header) => (
                      <th className="px-5 py-4" key={header}>
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {candidates.map((candidate) => {
                    const id = getCandidateId(candidate);
                    return (
                      <tr className="transition-colors hover:bg-brand-faint/40" key={id || candidate.name}>
                        <td className="px-5 py-4 text-[14px] font-semibold text-slate-900">
                          {candidate.name ?? "Unnamed Candidate"}
                        </td>
                        <td className="max-w-[220px] truncate px-5 py-4 text-[14px] text-[#77777a]">
                          {candidate.email ?? "-"}
                        </td>
                        <td className="px-5 py-4">
                          <SkillTags skills={candidate.skills ?? []} />
                        </td>
                        <td className="px-5 py-4 text-[14px] text-[#77777a]">
                          {candidate.work_rights || "-"}
                        </td>
                        <td className="px-5 py-4 text-[14px] text-[#77777a]">
                          {candidate.notice_period || "-"}
                        </td>
                        <td className="px-5 py-4">
                          {id ? (
                            <Link className="text-[14px] font-bold text-crimson-700 hover:text-[#ff1717]" href={`/candidates/${encodeURIComponent(id)}`}>
                              View Profile
                            </Link>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                  {candidates.length === 0 ? (
                    <tr>
                      <td className="px-5 py-8 text-center text-[14px] text-[#77777a]" colSpan={6}>
                        Upload CVs to populate this table.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </section>
    </>
  );
}

function RecentCandidateCard({ candidate }: { candidate: Candidate }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-4 transition hover:bg-white hover:shadow-sm">
      <div className="flex gap-4">
        <FileText className="mt-1 h-5 w-5 shrink-0 text-slate-400" />
        <div className="min-w-0">
          <p className="truncate text-[14px] font-semibold text-slate-900">
            {candidate.name ?? candidate.source_file ?? "Unnamed Candidate"}
          </p>
          <SkillTags skills={(candidate.skills ?? []).slice(0, 3)} />
          <p className="mt-2 text-[12px] text-[#a0a4ac]">
            {formatDate(candidate.created_at)}
          </p>
          <p className="mt-2 inline-flex items-center gap-1 text-[12px] font-bold text-[#00a650]">
            <CheckCircle2 className="h-4 w-4" />
            Processed
          </p>
        </div>
      </div>
    </div>
  );
}

function SkillTags({ skills }: { skills: string[] }) {
  if (skills.length === 0) {
    return <span className="text-[13px] text-[#9ca0a8]">-</span>;
  }

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {skills.slice(0, 3).map((skill) => (
        <Badge key={skill} tone="grey">
          {skill}
        </Badge>
      ))}
    </div>
  );
}
