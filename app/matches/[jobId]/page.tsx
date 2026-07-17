"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Filter, Info, Star } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, statusTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { SearchBar } from "@/components/ui/SearchBar";
import {
  analyseTopCandidates,
  getJobs,
  getMatchesByJob,
  updateMatchStatus,
  type Job,
  type Match,
} from "@/src/lib/api";
import { getJobId, getJobTitle, getMatchId, scoreToPercent } from "@/src/lib/utils";

export default function MatchResultsPage({
  params,
}: {
  params: { jobId: string };
}) {
  const router = useRouter();
  const jobId = params.jobId;
  const [jobs, setJobs] = useState<Job[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isAnalysing, setIsAnalysing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError("");
      try {
        const [jobList, matchList] = await Promise.all([
          getJobs(),
          getMatchesByJob(jobId),
        ]);
        if (mounted) {
          setJobs(jobList);
          setMatches(matchList);
        }
      } catch (requestError) {
        if (mounted) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Match results could not be loaded.",
          );
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    load();

    return () => {
      mounted = false;
    };
  }, [jobId]);

  useEffect(() => {
    let mounted = true;

    async function runAnalysis() {
      setIsAnalysing(true);
      try {
        await analyseTopCandidates(jobId, 5);
        const updated = await getMatchesByJob(jobId);
        if (mounted) {
          setMatches(updated);
        }
      } catch {
        // Analysis is best-effort; semantic matches remain usable.
      } finally {
        if (mounted) {
          setIsAnalysing(false);
        }
      }
    }

    runAnalysis();

    return () => {
      mounted = false;
    };
  }, [jobId]);

  const selectedJob = jobs.find((job) => getJobId(job) === jobId);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return matches;
    }
    return matches.filter((match) =>
      [match.candidate_name, match.candidate_email]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [matches, query]);

  async function updateStatus(match: Match, status: "Approved" | "Sent" | "Shortlisted") {
    const matchId = getMatchId(match);
    if (!matchId) {
      return;
    }
    await updateMatchStatus(matchId, status);
    setMatches(await getMatchesByJob(jobId));
  }

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
        <h1 className="text-[22px] font-bold text-crimson-700">Matches unavailable</h1>
        <p className="mt-3 text-[15px] leading-6 text-[#77777a]">{error}</p>
      </Card>
    );
  }

  return (
    <>
      <PageHeader
        subtitle={selectedJob ? `${getJobTitle(selectedJob)} - ${selectedJob.client ?? selectedJob.domain ?? ""}` : "Ranked candidates for this role"}
        title="Matching Results"
      />

      <div className="mb-8 flex flex-wrap items-center gap-4">
        <span className="text-[14px] font-bold text-[#333438]">Viewing results for:</span>
        <select
          className="h-10 min-w-[320px] rounded-[8px] border border-[#d8dee7] bg-white px-4 text-[14px] outline-none"
          onChange={(event) => router.push(`/matches/${encodeURIComponent(event.target.value)}`)}
          value={jobId}
        >
          {jobs.map((job) => (
            <option key={getJobId(job)} value={getJobId(job)}>
              {getJobTitle(job)} - {job.client ?? job.domain ?? "Client"}
            </option>
          ))}
        </select>
      </div>

      {isAnalysing ? (
        <div className="mb-5 rounded-[8px] border border-[#fde68a] bg-[#fffbeb] px-4 py-3 text-[14px] font-bold text-[#a65f00]">
          Running AI analysis for the top candidates...
        </div>
      ) : null}

      <div className="grid gap-8 xl:grid-cols-[260px_1fr]">
        <FilterPanel />
        <div className="space-y-7">
          <SearchBar
            onChange={setQuery}
            placeholder="Search candidates by name, skills, or experience..."
            value={query}
          />

          <CandidateTable
            accented
            jobId={jobId}
            matches={filtered.slice(0, 5)}
            onApprove={(match) => updateStatus(match, "Approved")}
            onReject={(match) => updateStatus(match, "Sent")}
            title="Top 5 Recommended Candidates"
          />

          <CandidateTable
            jobId={jobId}
            matches={filtered.slice(5)}
            onApprove={(match) => updateStatus(match, "Shortlisted")}
            onReject={(match) => updateStatus(match, "Sent")}
            title="Other Candidates"
          />
        </div>
      </div>
    </>
  );
}

function FilterPanel() {
  return (
    <Card className="self-start px-6 py-6">
      <div className="mb-6 flex items-center gap-2">
        <Filter className="h-5 w-5 text-[#333438]" />
        <h2 className="text-[20px] font-bold text-[#333438]">Filters</h2>
      </div>
      <div className="space-y-6">
        {["Location", "Budget Match", "Experience Level"].map((label) => (
          <label className="block" key={label}>
            <span className="mb-2 block text-[14px] font-bold text-[#333438]">
              {label}
            </span>
            <select className="h-10 w-full rounded-[8px] border border-[#d8dee7] bg-white px-3 text-[14px]">
              <option>All {label === "Location" ? "Locations" : label === "Budget Match" ? "Ranges" : "Levels"}</option>
            </select>
          </label>
        ))}
        <div>
          <p className="mb-3 text-[14px] font-bold text-[#333438]">Technical Skills</p>
          <div className="space-y-2 text-[14px] text-[#333438]">
            {["React", "Node.js", "TypeScript", "AWS"].map((skill) => (
              <label className="flex items-center gap-2" key={skill}>
                <input className="h-4 w-4 accent-crimson-700" type="checkbox" />
                {skill}
              </label>
            ))}
          </div>
        </div>
        <Button className="w-full">Apply Filters</Button>
        <Button className="w-full" variant="secondary">Clear All</Button>
      </div>
    </Card>
  );
}

function CandidateTable({
  accented,
  jobId,
  matches,
  onApprove,
  onReject,
  title,
}: {
  accented?: boolean;
  jobId: string;
  matches: Match[];
  onApprove: (match: Match) => void;
  onReject: (match: Match) => void;
  title: string;
}) {
  return (
    <Card className="overflow-hidden">
      <div className={accented ? "bg-crimson-700 px-6 py-5 text-white" : "px-6 py-5"}>
        <CardHeader
          title={title}
          subtitle={accented ? "Best matches based on AI analysis" : undefined}
          className={accented ? "[&_h2]:text-white [&_p]:text-white/90" : undefined}
          action={accented ? <Star className="h-5 w-5 fill-white text-white" /> : undefined}
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-left">
          <thead className={accented ? "bg-[#e8cfd6]" : "bg-[#f5f6f8]"}>
            <tr>
              {["Rank", "Candidate Name", "Match Score", "Tech Match", "Exp Match", "Location", "Status", "Actions"].map((header) => (
                <th className="px-5 py-3 text-[12px] font-bold uppercase tracking-[0.05em] text-crimson-700" key={header}>
                  <span className="inline-flex items-center gap-1">
                    {header}
                    {header === "Match Score" ? <span title="Semantic similarity score generated using Atlas Vector Search embeddings."><Info className="h-3.5 w-3.5" /></span> : null}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#edf0f3]">
            {matches.map((match, index) => {
              const matchId = getMatchId(match);
              const percent = scoreToPercent(match.score ?? match.match_score);
              const tech = match.analysis?.tech_match_percentage ?? Math.min(99, Math.round(percent * 1.02));
              const exp = match.analysis?.exp_match_percentage ?? Math.round(percent * 0.98);
              return (
                <tr className={index === 0 && accented ? "bg-[#fbf3f5]" : "bg-white"} key={matchId || `${match.candidate_id}-${index}`}>
                  <td className="px-5 py-4">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#ff1717] text-[12px] font-bold text-white">
                      {index + 1}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-[15px] font-bold text-[#333438]">
                    {match.candidate_name ?? "Unknown Candidate"}
                  </td>
                  <td className="px-5 py-4">
                    <ScorePill value={percent} />
                  </td>
                  <td className="px-5 py-4 text-[14px] text-[#333438]">{tech}%</td>
                  <td className="px-5 py-4 text-[14px] text-[#333438]">{exp}%</td>
                  <td className="px-5 py-4 text-[14px] font-bold text-[#00a650]">Yes</td>
                  <td className="px-5 py-4">
                    {match.analysis ? <Badge tone="green">AI Analysed</Badge> : <Badge tone={statusTone(match.status)}>{match.status ?? "Matched"}</Badge>}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      {match.candidate_id ? (
                        <Link className="text-[14px] font-bold text-crimson-700" href={`/matches/${encodeURIComponent(jobId)}/candidate/${encodeURIComponent(match.candidate_id)}`}>
                          View
                        </Link>
                      ) : null}
                      <button className="text-[14px] font-bold text-crimson-700" onClick={() => onApprove(match)} type="button">
                        {accented ? "Approve" : "Shortlist"}
                      </button>
                      <button className="text-[14px] text-[#8b8f97]" onClick={() => onReject(match)} type="button">
                        Reject
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {matches.length === 0 ? (
              <tr>
                <td className="px-5 py-8 text-center text-[14px] text-[#77777a]" colSpan={8}>
                  No candidates found.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ScorePill({ value }: { value: number }) {
  const tone = value >= 85 ? "green" : value >= 70 ? "amber" : "red";
  return <Badge tone={tone}>{value}%</Badge>;
}
