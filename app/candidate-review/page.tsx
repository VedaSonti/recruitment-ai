"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Save } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import {
  getJobs,
  getMatchesByJob,
  updateMatchStatus,
  type Job,
  type Match,
} from "@/src/lib/api";
import { formatDate, getJobId, getJobTitle, getMatchId, initials, scoreToPercent } from "@/src/lib/utils";

type Disposition = "" | "Willing" | "Not Willing" | "No Show / Disappeared";

const statusMap: Record<Exclude<Disposition, "">, "Approved" | "Sent" | "Matched"> = {
  Willing: "Approved",
  "Not Willing": "Sent",
  "No Show / Disappeared": "Matched",
};

export default function CandidateReviewPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({});
  const [toast, setToast] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function loadJobs() {
      setIsLoading(true);
      const nextJobs = await getJobs();
      if (mounted) {
        setJobs(nextJobs);
        setSelectedJobId(getJobId(nextJobs[0] ?? {}));
      }
    }
    loadJobs().catch(() => setIsLoading(false));
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    async function loadMatches() {
      if (!selectedJobId) {
        setMatches([]);
        setIsLoading(false);
        return;
      }
      setIsLoading(true);
      const nextMatches = await getMatchesByJob(selectedJobId);
      if (mounted) {
        setMatches(nextMatches);
        setIsLoading(false);
      }
    }
    loadMatches().catch(() => setIsLoading(false));
    return () => {
      mounted = false;
    };
  }, [selectedJobId]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(""), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const progress = useMemo(
    () => ({
      approved: matches.filter((match) => match.status === "Approved").length,
      rejected: matches.filter((match) => match.status === "Sent").length,
      pending: matches.filter((match) => (match.status ?? "Matched") === "Matched").length,
      total: matches.length,
    }),
    [matches],
  );

  async function save(match: Match) {
    const id = getMatchId(match);
    const disposition = dispositions[id];
    if (!id || !disposition) {
      return;
    }
    await updateMatchStatus(id, statusMap[disposition], notes[id] ?? "");
    setMatches(await getMatchesByJob(selectedJobId));
  }

  async function moveNext(match: Match) {
    const id = getMatchId(match);
    if (!id) {
      return;
    }
    await updateMatchStatus(id, "Shortlisted", notes[id] ?? "");
    setMatches(await getMatchesByJob(selectedJobId));
  }

  return (
    <>
      <PageHeader
        subtitle="Update candidate disposition and add validation notes"
        title="Candidate Review"
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <span className="text-[14px] font-bold text-[#333438]">Reviewing candidates for:</span>
        <select
          className="h-10 min-w-[320px] rounded-[8px] border border-[#d8dee7] bg-white px-4 text-[14px]"
          onChange={(event) => setSelectedJobId(event.target.value)}
          value={selectedJobId}
        >
          {jobs.map((job) => (
            <option key={getJobId(job)} value={getJobId(job)}>
              {getJobTitle(job)}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="flex min-h-[420px] items-center justify-center">
          <LoadingSpinner size="lg" />
        </div>
      ) : (
        <div className="grid items-start gap-8 xl:grid-cols-[1fr_320px]">
          <div className="space-y-5">
            {matches.map((match) => {
              const id = getMatchId(match);
              const selected = dispositions[id] ?? "";
              return (
                <Card className="px-6 py-6" key={id}>
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div className="flex gap-4">
                      <Avatar name={match.candidate_name ?? "Candidate"} />
                      <div>
                        <h2 className="text-[20px] font-bold text-[#333438]">
                          {match.candidate_name ?? "Candidate"}
                        </h2>
                        <p className="mt-2 text-[14px] text-[#77777a]">
                          Match Score: <Badge tone="green">{scoreToPercent(match.score)}%</Badge>
                        </p>
                      </div>
                    </div>
                    {match.candidate_id ? (
                      <Link className="text-[14px] font-bold text-crimson-700" href={`/matches/${encodeURIComponent(selectedJobId)}/candidate/${encodeURIComponent(match.candidate_id)}`}>
                        View Details {"->"}
                      </Link>
                    ) : null}
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <label>
                      <span className="mb-2 block text-[14px] font-bold text-[#333438]">
                        Disposition Status *
                      </span>
                      <select
                        className="h-11 w-full rounded-[8px] border border-[#d8dee7] bg-white px-4 text-[15px]"
                        onChange={(event) => setDispositions((current) => ({ ...current, [id]: event.target.value as Disposition }))}
                        value={selected}
                      >
                        <option value="">Select Status</option>
                        <option>Willing</option>
                        <option>Not Willing</option>
                        <option>No Show / Disappeared</option>
                      </select>
                    </label>
                    {selected === "Willing" ? (
                      <div className="mt-7 flex h-11 items-center justify-center gap-2 rounded-[8px] bg-[#d9f8e5] text-[14px] font-bold text-[#04743b]">
                        <CheckCircle2 className="h-4 w-4" />
                        Willing to Proceed
                      </div>
                    ) : null}
                  </div>

                  <label className="mt-5 block">
                    <span className="mb-2 block text-[14px] font-bold text-[#333438]">Recruiter Notes</span>
                    <textarea
                      className="min-h-[90px] w-full resize-none rounded-[8px] border border-[#d8dee7] px-4 py-3 text-[15px] outline-none focus:border-crimson-700"
                      onChange={(event) => setNotes((current) => ({ ...current, [id]: event.target.value }))}
                      placeholder="Add validation notes, interview feedback, or special considerations..."
                      value={notes[id] ?? ""}
                    />
                  </label>

                  <div className="mt-5">
                    <p className="mb-3 text-[14px] font-bold text-[#333438]">Feedback History</p>
                    <div className="overflow-hidden rounded-[8px] border border-[#E5E7EB]">
                      <table className="w-full border-collapse text-left">
                        <thead className="bg-[#e8cfd6]">
                          <tr>
                            {["Date", "Action", "Comments"].map((header) => (
                              <th className="px-4 py-3 text-[12px] font-bold uppercase text-crimson-700" key={header}>{header}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {match.status_note ? (
                            <tr>
                              <td className="px-4 py-3 text-[13px] text-[#77777a]">{formatDate(match.updated_at ?? match.created_at)}</td>
                              <td className="px-4 py-3"><Badge tone="green">{match.status ?? "Note"}</Badge></td>
                              <td className="px-4 py-3 text-[13px] text-[#555b66]">{match.status_note}</td>
                            </tr>
                          ) : (
                            <tr>
                              <td className="px-4 py-5 text-center text-[13px] text-[#9ca0a8]" colSpan={3}>No feedback recorded yet</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-wrap gap-3">
                    <Button leftIcon={<Save className="h-4 w-4" />} onClick={() => save(match)}>
                      Save Status
                    </Button>
                    <Button onClick={() => moveNext(match)} rightIcon={<ArrowRight className="h-4 w-4" />} variant="secondary">
                      Move to Next Stage
                    </Button>
                  </div>
                </Card>
              );
            })}
            {matches.length === 0 ? (
              <Card className="px-6 py-10 text-center text-[14px] text-[#77777a]">
                No matches available for this job.
              </Card>
            ) : null}
          </div>

          <Card className="self-start px-6 py-6">
            <CardHeader className="mb-5" title="Review Progress" />
            <ProgressCard label="Total Candidates" value={progress.total} />
            <ProgressCard label="Approved" tone="green" value={progress.approved} />
            <ProgressCard label="Rejected" tone="red" value={progress.rejected} />
            <ProgressCard label="Pending" tone="amber" value={progress.pending} />
            <div className="mt-6 border-t border-[#E5E7EB] pt-5">
              <h3 className="mb-4 text-[17px] font-bold text-[#333438]">Quick Actions</h3>
              <div className="space-y-2">
                <Button className="w-full" onClick={() => setToast("Coming soon")} variant="secondary">Export Report</Button>
                <Button className="w-full" onClick={() => setToast("Coming soon")} variant="secondary">Send Reminders</Button>
                {selectedJobId ? (
                  <Link href={`/matches/${encodeURIComponent(selectedJobId)}`}>
                    <Button className="mt-2 w-full">View Final Selection</Button>
                  </Link>
                ) : null}
              </div>
              {toast ? <p className="mt-3 text-center text-[13px] font-bold text-crimson-700">{toast}</p> : null}
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

function Avatar({ name }: { name: string }) {
  return (
    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[#b70735] text-[16px] font-bold text-white">
      {initials(name)}
    </span>
  );
}

function ProgressCard({
  label,
  tone,
  value,
}: {
  label: string;
  tone?: "green" | "red" | "amber";
  value: number;
}) {
  return (
    <div className={`mb-4 rounded-[8px] border px-4 py-4 ${
      tone === "green" ? "border-[#b7efc9] bg-[#effbf3] text-[#04743b]" :
      tone === "red" ? "border-[#fecaca] bg-[#fff1f1] text-[#b91c1c]" :
      tone === "amber" ? "border-[#fde68a] bg-[#fffbea] text-[#a65f00]" :
      "border-[#E5E7EB] bg-white text-[#333438]"
    }`}>
      <p className="text-[14px]">{label}</p>
      <p className="mt-3 text-[26px] font-bold">{value}</p>
    </div>
  );
}
