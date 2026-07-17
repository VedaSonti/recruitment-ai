"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, FileText } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, statusTone } from "@/components/ui/Badge";
import { Card, CardHeader } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { UploadWorkflow } from "@/components/upload/UploadWorkflow";
import {
  getJobs,
  getMatchesByJob,
  uploadJob,
  type Job,
} from "@/src/lib/api";
import { formatDate, getClient, getJobId, getJobTitle } from "@/src/lib/utils";

export default function UploadJobPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [matchCounts, setMatchCounts] = useState<Record<string, number>>({});
  const [isLoading, setIsLoading] = useState(true);

  const loadJobs = useCallback(async () => {
    setIsLoading(true);
    const nextJobs = await getJobs();
    const counts = await Promise.all(
      nextJobs.map(async (job) => {
        const id = getJobId(job);
        if (!id) {
          return [id, 0] as const;
        }
        return [id, (await getMatchesByJob(id)).length] as const;
      }),
    );
    setJobs(nextJobs);
    setMatchCounts(Object.fromEntries(counts));
    setIsLoading(false);
  }, []);

  useEffect(() => {
    loadJobs().catch(() => setIsLoading(false));
  }, [loadJobs]);

  return (
    <>
      <PageHeader
        subtitle="GPT will automatically extract all job details and match against existing candidates. Supports bulk upload."
        title="Upload Job Description"
      />

      <div className="grid items-start gap-8 xl:grid-cols-[2fr_0.95fr]">
        <div className="space-y-7">
          <UploadWorkflow
            dropTitle="Drag and drop your JD files here"
            helperText="PDF or DOCX - Multiple files supported"
            manualDetails
            onProcessed={() => loadJobs()}
            upload={uploadJob}
          />
        </div>

        <Card className="self-start px-6 py-6">
          <CardHeader className="mb-5" title="Uploaded Jobs" />
          {isLoading ? (
            <div className="flex justify-center py-10">
              <LoadingSpinner />
            </div>
          ) : (
            <div className="space-y-4">
              {jobs.slice(0, 3).map((job) => (
                <RecentJobCard job={job} key={getJobId(job) || getJobTitle(job)} />
              ))}
              {jobs.length === 0 ? (
                <p className="py-6 text-center text-[14px] text-[#77777a]">
                  No jobs uploaded yet.
                </p>
              ) : null}
            </div>
          )}
        </Card>
      </div>

      <section className="mt-8">
        <h2 className="mb-4 text-[18px] font-bold text-[#333438]">Uploaded Jobs</h2>
        <Card className="overflow-hidden">
          {isLoading ? (
            <div className="flex justify-center py-12">
              <LoadingSpinner />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] border-collapse text-left">
                <thead className="bg-[#f5f6f8]">
                  <tr>
                    {["Job Title", "Client", "Upload Date", "Status", "Candidates Matched", "View Matches"].map((header) => (
                      <th className="px-5 py-4 text-[12px] font-bold uppercase tracking-[0.06em] text-[#9ca0a8]" key={header}>
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#edf0f3]">
                  {jobs.map((job) => {
                    const id = getJobId(job);
                    return (
                      <tr key={id || getJobTitle(job)}>
                        <td className="px-5 py-4 text-[14px] font-bold text-[#333438]">
                          {getJobTitle(job)}
                        </td>
                        <td className="px-5 py-4 text-[14px] text-[#77777a]">{getClient(job)}</td>
                        <td className="px-5 py-4 text-[14px] text-[#77777a]">{formatDate(job.created_at)}</td>
                        <td className="px-5 py-4">
                          <Badge tone={statusTone(job.status)}>{job.status ?? "Open"}</Badge>
                        </td>
                        <td className="px-5 py-4 text-[14px] text-[#333438]">{matchCounts[id] ?? 0}</td>
                        <td className="px-5 py-4">
                          {id ? (
                            <Link className="text-[14px] font-bold text-crimson-700 hover:text-[#ff1717]" href={`/matches/${encodeURIComponent(id)}`}>
                              View Matches
                            </Link>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                  {jobs.length === 0 ? (
                    <tr>
                      <td className="px-5 py-8 text-center text-[14px] text-[#77777a]" colSpan={6}>
                        Upload job descriptions to populate this table.
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

function RecentJobCard({ job }: { job: Job }) {
  return (
    <div className="rounded-[8px] border border-[#E5E7EB] px-4 py-4">
      <div className="flex gap-4">
        <FileText className="mt-1 h-5 w-5 shrink-0 text-crimson-700" />
        <div className="min-w-0">
          <p className="truncate text-[14px] font-bold text-[#333438]">
            {getJobTitle(job)}
          </p>
          <p className="mt-1 truncate text-[12px] text-[#77777a]">{getClient(job)}</p>
          <p className="mt-1 text-[12px] text-[#a0a4ac]">{formatDate(job.created_at)}</p>
          <p className="mt-2 inline-flex items-center gap-1 text-[12px] font-bold text-[#00a650]">
            <CheckCircle2 className="h-4 w-4" />
            Processed
          </p>
        </div>
      </div>
    </div>
  );
}
