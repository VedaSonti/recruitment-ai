"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Database, FileUp, Upload, Users } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, statusTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { StatCard } from "@/components/ui/StatCard";
import {
  getCandidates,
  getJobs,
  getMatchesByJob,
  type Candidate,
  type Job,
  type Match,
} from "@/src/lib/api";
import {
  formatDate,
  getCandidateId,
  getClient,
  getJobId,
  getJobTitle,
} from "@/src/lib/utils";

type JobMeta = Record<string, { candidates: number; shortlisted: number }>;

export default function DashboardPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [jobMeta, setJobMeta] = useState<JobMeta>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadDashboard() {
      setIsLoading(true);
      setError("");

      try {
        const [jobList, candidateList] = await Promise.all([
          getJobs(),
          getCandidates(),
        ]);

        const matchPairs = await Promise.all(
          jobList.map(async (job) => {
            const jobId = getJobId(job);
            if (!jobId) {
              return [jobId, [] as Match[]] as const;
            }
            return [jobId, await getMatchesByJob(jobId)] as const;
          }),
        );

        const metaPairs = matchPairs.map(([jobId, jobMatches]) => [
          jobId,
          {
            candidates: jobMatches.length,
            shortlisted: jobMatches.filter(
              (match) => match.status === "Shortlisted",
            ).length,
          },
        ] as const);

        const allMatches = matchPairs.flatMap(([, jobMatches]) => jobMatches);

        if (mounted) {
          setJobs(jobList);
          setCandidates(candidateList);
          setMatches(allMatches);
          setJobMeta(Object.fromEntries(metaPairs));
        }
      } catch (requestError) {
        if (mounted) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Dashboard data could not be loaded.",
          );
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    loadDashboard();

    return () => {
      mounted = false;
    };
  }, []);

  const activeJobs = jobs.filter((job) => (job.status ?? "Open") === "Open");
  const awaitingReview = useMemo(() => {
    const awaitingCandidateIds = new Set(
      matches
        .filter((match) => match.status === "Matched")
        .map((match) => match.candidate_id)
        .filter(Boolean),
    );
    return awaitingCandidateIds.size;
  }, [matches]);

  const shortlisted = useMemo(() => {
    const shortlistedIds = new Set(
      matches
        .filter((match) =>
          ["Shortlisted", "Interview Sent", "Interview Completed"].includes(match.status ?? ""),
        )
        .map((match) => match.candidate_id)
        .filter(Boolean),
    );
    return shortlistedIds.size;
  }, [matches]);

  if (isLoading) {
    return (
      <div className="flex min-h-[520px] items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="mx-auto max-w-xl px-6 py-10 text-center">
        <h1 className="text-[22px] font-bold text-crimson-700">
          Dashboard unavailable
        </h1>
        <p className="mt-3 text-[15px] leading-6 text-[#77777a]">{error}</p>
      </Card>
    );
  }

  return (
    <>
      <PageHeader
        subtitle="Welcome back, Sarah. Here's your recruitment overview."
        title="Dashboard"
      />

      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <StatCard accent="crimson" label="Active Job Descriptions" value={activeJobs.length} />
        <StatCard accent="green" label="Total Candidates" value={candidates.length} />
        <StatCard accent="amber" label="Candidates Awaiting Review" value={awaitingReview} />
        <StatCard accent="red" label="Shortlisted Candidates" value={shortlisted} />
      </div>

      <section className="mt-9">
        <h2 className="mb-4 text-[22px] font-bold text-[#333438]">Quick Actions</h2>
        <div className="grid gap-4 lg:grid-cols-3">
          <Link href="/upload-job">
            <Button className="w-full" leftIcon={<Upload className="h-5 w-5" />} size="lg">
              Upload Job Description
            </Button>
          </Link>
          <Link href="/upload-cvs">
            <Button className="w-full" leftIcon={<Users className="h-5 w-5" />} size="lg">
              Upload Candidate CVs
            </Button>
          </Link>
          <Link href="/candidate-review">
            <Button className="w-full" leftIcon={<Database className="h-5 w-5" />} size="lg" variant="secondary">
              Candidate Database
            </Button>
          </Link>
        </div>
      </section>

      <div className="mt-8 grid gap-7 xl:grid-cols-[1.35fr_0.65fr]">
        <Card className="overflow-hidden">
          <CardHeader className="px-6 py-5" title="Recent Jobs" />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead className="bg-[#e8cfd6]">
                <tr>
                  {["Job Title", "Client", "Candidates", "Shortlisted", "Status", "Actions"].map((header) => (
                    <th className="px-6 py-3 text-[12px] font-bold uppercase tracking-[0.04em] text-crimson-700" key={header}>
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#edf0f3]">
                {jobs.slice(0, 6).map((job) => {
                  const id = getJobId(job);
                  const meta = jobMeta[id] ?? { candidates: 0, shortlisted: 0 };
                  return (
                    <tr className="hover:bg-[#fbf7f8]" key={id || getJobTitle(job)}>
                      <td className="px-6 py-4 text-[14px] font-bold text-[#333438]">
                        {getJobTitle(job)}
                      </td>
                      <td className="px-6 py-4 text-[14px] text-[#77777a]">{getClient(job)}</td>
                      <td className="px-6 py-4 text-[14px] text-[#333438]">{meta.candidates}</td>
                      <td className="px-6 py-4 text-[14px] font-bold text-[#ff1717]">{meta.shortlisted}</td>
                      <td className="px-6 py-4">
                        <Badge tone={statusTone(job.status)}>{job.status ?? "Open"}</Badge>
                      </td>
                      <td className="px-6 py-4">
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
                    <td className="px-6 py-8 text-center text-[14px] text-[#77777a]" colSpan={6}>
                      No jobs uploaded yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="px-6 py-5">
          <CardHeader className="mb-4" title="Recent Candidates" />
          <div className="space-y-3">
            {candidates.slice(0, 5).map((candidate) => {
              const id = getCandidateId(candidate);
              return (
                <div className="rounded-[8px] border border-[#E5E7EB] px-4 py-3" key={id || candidate.name}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[14px] font-bold text-[#333438]">
                        {candidate.name ?? "Unnamed Candidate"}
                      </p>
                      <p className="mt-1 truncate text-[12px] text-[#77777a]">
                        {candidate.email ?? "No email"}
                      </p>
                      <p className="mt-1 text-[12px] text-[#9ca0a8]">
                        {formatDate(candidate.created_at)}
                      </p>
                    </div>
                    <FileUp className="h-5 w-5 text-[#98a2b3]" />
                  </div>
                  {id ? (
                    <Link className="mt-2 inline-block text-[13px] font-bold text-crimson-700" href={`/candidates/${encodeURIComponent(id)}`}>
                      View Profile
                    </Link>
                  ) : null}
                </div>
              );
            })}
            {candidates.length === 0 ? (
              <p className="py-6 text-center text-[14px] text-[#77777a]">
                No candidates uploaded yet.
              </p>
            ) : null}
          </div>
        </Card>
      </div>
    </>
  );
}
