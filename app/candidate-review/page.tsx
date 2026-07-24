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
  getInterviewByMatch,
  getJobs,
  getMatchesByJob,
  isAPIError,
  scheduleInterview,
  updateMatchStatus,
  type Job,
  type Match,
  type MatchStatus,
} from "@/src/lib/api";
import {
  formatDate,
  getJobId,
  getJobTitle,
  getMatchId,
  initials,
  scoreToPercent,
} from "@/src/lib/utils";

type Disposition = "" | "Willing" | "Not Willing" | "No Show / Disappeared";
type InterviewResult = Awaited<ReturnType<typeof getInterviewByMatch>> & {
  video_analysis: {
    confidence_score: number;
    eye_contact: string;
    presentation: string;
    body_language: string;
    communication_clarity: string;
    engagement_over_time: string;
    flags: string[];
  } | null;
};

type FeedbackRow = {
  action: string;
  comments: string;
  date: string;
};

type RowActionState = Record<
  string,
  {
    bannerMessage?: string;
    bannerTone?: "success" | "error";
    message?: string;
    messageTone?: "success" | "error";
    moving?: boolean;
    saving?: boolean;
    scheduling?: boolean;
    viewingResults?: boolean;
  }
>;

const statusMap: Record<Exclude<Disposition, "">, "Shortlisted" | "Sent" | "Matched"> = {
  Willing: "Shortlisted",
  "Not Willing": "Sent",
  "No Show / Disappeared": "Matched",
};

const approvedStatuses = [
  "Approved",
  "Shortlisted",
  "Interview Sent",
  "Interview Completed",
  "Uplifted",
];

export default function CandidateReviewPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [matches, setMatches] = useState<Match[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({});
  const [unlockedDispositions, setUnlockedDispositions] = useState<Record<string, boolean>>({});
  const [feedbackRows, setFeedbackRows] = useState<Record<string, FeedbackRow[]>>({});
  const [rowActions, setRowActions] = useState<RowActionState>({});
  const [interviewResult, setInterviewResult] = useState<InterviewResult | null>(null);
  const [showInterviewModal, setShowInterviewModal] = useState(false);
  const [activeInterviewMatchId, setActiveInterviewMatchId] = useState("");
  const [modalActionLoading, setModalActionLoading] = useState<"uplift" | "reject" | null>(null);
  const [isRefreshingInterview, setIsRefreshingInterview] = useState(false);
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
        setFeedbackRows({});
        setRowActions({});
        setUnlockedDispositions({});
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      const nextMatches = await getMatchesByJob(selectedJobId);
      if (mounted) {
        setMatches(nextMatches);
        setFeedbackRows({});
        setRowActions({});
        setUnlockedDispositions({});
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
      approved: matches.filter((match) => approvedStatuses.includes(match.status ?? "")).length,
      rejected: matches.filter((match) => match.status === "Sent").length,
      pending: matches.filter((match) => (match.status ?? "Matched") === "Matched").length,
      total: matches.length,
    }),
    [matches],
  );

  function patchMatch(matchId: string, update: Partial<Match>) {
    setMatches((current) =>
      current.map((match) =>
        getMatchId(match) === matchId ? ({ ...match, ...update } as Match) : match,
      ),
    );
  }

  async function refreshMatchesForCurrentJob() {
    if (!selectedJobId) {
      return;
    }

    try {
      const nextMatches = await getMatchesByJob(selectedJobId);
      setMatches(nextMatches);
    } catch {
      // Keep the current card state if the background refresh fails.
    }
  }

  async function refreshMatchStatus(matchId: string) {
    if (!selectedJobId) {
      return;
    }

    try {
      const fresh = await getMatchesByJob(selectedJobId);
      setMatches((current) =>
        current.map((match) => {
          const updated = fresh.find((item) => getMatchId(item) === getMatchId(match));
          return updated && getMatchId(match) === matchId
            ? ({ ...match, status: updated.status, updated_at: updated.updated_at } as Match)
            : match;
        }),
      );
    } catch {
      // Silent fail: this is a lightweight status check.
    }
  }

  async function closeInterviewModal() {
    setShowInterviewModal(false);
    setInterviewResult(null);
    setActiveInterviewMatchId("");
    await refreshMatchesForCurrentJob();
  }

  function setRowLoading(matchId: string, update: Partial<RowActionState[string]>) {
    setRowActions((current) => ({
      ...current,
      [matchId]: {
        ...current[matchId],
        ...update,
      },
    }));
  }

  function clearRowBanner(matchId: string) {
    setRowLoading(matchId, {
      bannerMessage: undefined,
      bannerTone: undefined,
    });
  }

  function showRowMessage(
    matchId: string,
    message: string,
    messageTone: "success" | "error",
  ) {
    setRowLoading(matchId, { message, messageTone });
    window.setTimeout(() => {
      setRowActions((current) => {
        if (current[matchId]?.message !== message) {
          return current;
        }

        return {
          ...current,
          [matchId]: {
            ...current[matchId],
            message: undefined,
            messageTone: undefined,
          },
        };
      });
    }, 3000);
  }

  async function save(match: Match) {
    const id = getMatchId(match);
    const disposition = dispositions[id];

    if (!id) {
      return;
    }

    if (!disposition) {
      showRowMessage(id, "Please select a status before saving", "error");
      return;
    }

    const status = statusMap[disposition];
    const note = notes[id] ?? "";
    const now = new Date().toISOString();

    setRowLoading(id, {
      message: undefined,
      messageTone: undefined,
      saving: true,
    });

    try {
      await updateMatchStatus(id, status, note);
      patchMatch(id, {
        status,
        status_note: note,
        updated_at: now,
      });
      if (status === "Shortlisted") {
        setUnlockedDispositions((current) => ({ ...current, [id]: false }));
      }
      setFeedbackRows((current) => ({
        ...current,
        [id]: [
          ...(current[id] ?? []),
          {
            action: status,
            comments: note,
            date: now,
          },
        ],
      }));
      setRowLoading(id, { saving: false });
      showRowMessage(id, "\u2713 Status saved", "success");
    } catch {
      setRowLoading(id, { saving: false });
      showRowMessage(id, "Failed to save \u2014 try again", "error");
    }
  }

  async function moveNext(match: Match) {
    const id = getMatchId(match);

    if (!id) {
      return;
    }

    const currentStatus = (match.status ?? "Matched") as MatchStatus;

    setRowLoading(id, {
      bannerMessage: undefined,
      bannerTone: undefined,
      message: undefined,
      messageTone: undefined,
      moving: true,
    });

    if (currentStatus === "Shortlisted") {
      try {
        const result = await scheduleInterview(id);
        patchMatch(id, {
          status: "Interview Sent",
          updated_at: new Date().toISOString(),
        });
        setRowLoading(id, {
          bannerMessage: `\u2713 Interview invitation sent to ${result.candidate_email}`,
          bannerTone: "success",
          moving: false,
        });
      } catch (error) {
        const message =
          isAPIError(error) && error.status === 400
            ? "Cannot schedule \u2014 no email address on file for this candidate."
            : error instanceof Error
              ? error.message
              : "Failed to schedule interview.";

        setRowLoading(id, {
          bannerMessage: message,
          bannerTone: "error",
          moving: false,
        });
      }
      return;
    }

    const nextStatus: MatchStatus | null =
      currentStatus === "Approved"
        ? "Shortlisted"
        : currentStatus === "Matched"
          ? "Approved"
          : null;

    if (!nextStatus) {
      setRowLoading(id, { moving: false });
      showRowMessage(id, "Candidate must be Matched, Approved, or Shortlisted before moving", "error");
      return;
    }

    try {
      await updateMatchStatus(id, nextStatus);
      patchMatch(id, {
        status: nextStatus,
        updated_at: new Date().toISOString(),
      });
      setRowLoading(id, { moving: false });
      showRowMessage(id, "\u2713 Moved to next stage", "success");
    } catch {
      setRowLoading(id, { moving: false });
      showRowMessage(id, "Failed to move \u2014 try again", "error");
    }
  }

  async function schedule(match: Match) {
    const id = getMatchId(match);

    if (!id) {
      return;
    }

    setRowLoading(id, {
      bannerMessage: undefined,
      bannerTone: undefined,
      scheduling: true,
    });

    try {
      const result = await scheduleInterview(id);
      patchMatch(id, {
        status: "Interview Sent",
        updated_at: new Date().toISOString(),
      });
      setRowLoading(id, {
        bannerMessage: `\u2713 Interview invitation sent to ${result.candidate_email}`,
        bannerTone: "success",
        scheduling: false,
      });
    } catch (error) {
      const message =
        isAPIError(error) && error.status === 400
          ? "Cannot schedule \u2014 no email address on file for this candidate."
          : error instanceof Error
            ? error.message
            : "Failed to schedule interview.";

      setRowLoading(id, {
        bannerMessage: message,
        bannerTone: "error",
        scheduling: false,
      });
    }
  }

  async function viewInterviewResults(match: Match) {
    const id = getMatchId(match);

    if (!id) {
      return;
    }

    setRowLoading(id, {
      bannerMessage: undefined,
      bannerTone: undefined,
      viewingResults: true,
    });

    try {
      const result = await getInterviewByMatch(id);
      setInterviewResult(result as InterviewResult);
      setActiveInterviewMatchId(id);
      setShowInterviewModal(true);
      setRowLoading(id, { viewingResults: false });
    } catch (error) {
      setRowLoading(id, {
        bannerMessage: error instanceof Error ? error.message : "Failed to load interview results.",
        bannerTone: "error",
        viewingResults: false,
      });
    }
  }

  async function refreshInterviewResults() {
    if (!activeInterviewMatchId) {
      return;
    }

    setIsRefreshingInterview(true);

    try {
      const result = await getInterviewByMatch(activeInterviewMatchId);
      setInterviewResult(result as InterviewResult);
      await refreshMatchesForCurrentJob();
    } finally {
      setIsRefreshingInterview(false);
    }
  }

  async function completeFromModal(status: "Uplifted" | "Sent") {
    if (!activeInterviewMatchId) {
      return;
    }

    setModalActionLoading(status === "Uplifted" ? "uplift" : "reject");

    try {
      await updateMatchStatus(activeInterviewMatchId, status);
      patchMatch(activeInterviewMatchId, {
        status,
        updated_at: new Date().toISOString(),
      });
      await closeInterviewModal();
    } finally {
      setModalActionLoading(null);
    }
  }

  return (
    <>
      <PageHeader
        subtitle="Update candidate disposition and add validation notes"
        title="Candidate Review"
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <span className="text-[14px] font-bold text-[#333438]">
          Reviewing candidates for:
        </span>
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
              const actionState = rowActions[id] ?? {};
              const status = match.status ?? "Matched";
              const selected = dispositions[id] ?? (status === "Shortlisted" ? "Willing" : "");
              const lockedWilling = status === "Shortlisted" && !unlockedDispositions[id];
              const interviewDone = ["Interview Completed", "Assessed", "Uplifted", "Sent"].includes(status);
              const canCheckInterviewResults = status === "Interview Sent";
              const feedback = feedbackRows[id]?.length
                ? feedbackRows[id]
                : match.status_note
                  ? [
                      {
                        action: match.status ?? "Note",
                        comments: match.status_note,
                        date: match.updated_at ?? match.created_at ?? "",
                      },
                    ]
                  : [];

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
                        <div className="mt-3 flex flex-wrap items-center gap-3 text-[14px] text-[#77777a]">
                          <span>
                            Status: <Badge tone={reviewStatusTone(status)}>{status}</Badge>
                          </span>
                          {status === "Shortlisted" ? (
                            <Button
                              className="border-crimson-700 text-crimson-700 hover:bg-[#fff5f7]"
                              isLoading={actionState.scheduling}
                              onClick={() => schedule(match)}
                              size="sm"
                              variant="secondary"
                            >
                              Schedule AI Interview
                            </Button>
                          ) : null}
                          {status === "Interview Sent" ? (
                            <>
                              <Badge className="bg-[#edf0f4] text-[#667085]" tone="grey">
                                Interview Invited
                              </Badge>
                              <button
                                className="flex items-center gap-1 text-[12px] text-gray-400 hover:text-gray-600"
                                onClick={() => refreshMatchStatus(id)}
                                type="button"
                              >
                                {"\u21bb"} Refresh status
                              </button>
                            </>
                          ) : null}
                          {interviewDone || canCheckInterviewResults ? (
                            <>
                              {interviewDone ? <Badge tone={reviewStatusTone(status)}>{status} {"\u2713"}</Badge> : null}
                              <button
                                className="inline-flex items-center gap-2 text-[14px] font-bold text-crimson-700 disabled:opacity-60"
                                disabled={actionState.viewingResults}
                                onClick={() => viewInterviewResults(match)}
                                type="button"
                              >
                                {actionState.viewingResults ? <LoadingSpinner size="sm" /> : null}
                                {canCheckInterviewResults ? "Check for Results" : "View Results"} {"\u2192"}
                              </button>
                            </>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    {match.candidate_id ? (
                      <Link
                        className="text-[14px] font-bold text-crimson-700"
                        href={`/matches/${encodeURIComponent(selectedJobId)}/candidate/${encodeURIComponent(match.candidate_id)}`}
                      >
                        View Details {"->"}
                      </Link>
                    ) : null}
                  </div>

                  {actionState.bannerMessage ? (
                    <div
                      className={`mb-5 flex items-start justify-between gap-3 rounded-[8px] border px-4 py-3 text-[13px] font-bold ${
                        actionState.bannerTone === "success"
                          ? "border-[#b7efc9] bg-[#effbf3] text-[#04743b]"
                          : "border-[#fecaca] bg-[#fff1f1] text-[#b91c1c]"
                      }`}
                    >
                      <span>{actionState.bannerMessage}</span>
                      {actionState.bannerTone === "success" ? (
                        <button
                          aria-label="Dismiss interview invitation message"
                          className="text-[18px] leading-none"
                          onClick={() => clearRowBanner(id)}
                          type="button"
                        >
                          {"\u00d7"}
                        </button>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="grid gap-4 md:grid-cols-2">
                    {lockedWilling ? (
                      <div>
                        <span className="mb-2 block text-[14px] font-bold text-[#333438]">
                          Disposition Status *
                        </span>
                        <div className="flex h-11 items-center gap-3">
                          <span className="inline-flex h-11 items-center gap-2 rounded-[8px] bg-[#d9f8e5] px-4 text-[14px] font-bold text-[#04743b]">
                            <CheckCircle2 className="h-4 w-4" />
                            Willing {"\u2014"} Shortlisted
                          </span>
                          <button
                            className="text-[13px] font-bold text-[#77777a] hover:text-crimson-700"
                            onClick={() => setUnlockedDispositions((current) => ({ ...current, [id]: true }))}
                            type="button"
                          >
                            Change
                          </button>
                        </div>
                      </div>
                    ) : (
                      <label>
                        <span className="mb-2 block text-[14px] font-bold text-[#333438]">
                          Disposition Status *
                        </span>
                        <select
                          className="h-11 w-full rounded-[8px] border border-[#d8dee7] bg-white px-4 text-[15px]"
                          onChange={(event) =>
                            setDispositions((current) => ({
                              ...current,
                              [id]: event.target.value as Disposition,
                            }))
                          }
                          value={selected}
                        >
                          <option value="">Select Status</option>
                          <option>Willing</option>
                          <option>Not Willing</option>
                          <option>No Show / Disappeared</option>
                        </select>
                      </label>
                    )}
                    {selected === "Willing" && !lockedWilling ? (
                      <div className="mt-7 flex h-11 items-center justify-center gap-2 rounded-[8px] bg-[#d9f8e5] text-[14px] font-bold text-[#04743b]">
                        <CheckCircle2 className="h-4 w-4" />
                        Willing to Proceed
                      </div>
                    ) : null}
                  </div>

                  <label className="mt-5 block">
                    <span className="mb-2 block text-[14px] font-bold text-[#333438]">
                      Recruiter Notes
                    </span>
                    <textarea
                      className="min-h-[90px] w-full resize-none rounded-[8px] border border-[#d8dee7] px-4 py-3 text-[15px] outline-none focus:border-crimson-700"
                      onChange={(event) =>
                        setNotes((current) => ({ ...current, [id]: event.target.value }))
                      }
                      placeholder="Add validation notes, interview feedback, or special considerations..."
                      value={notes[id] ?? ""}
                    />
                  </label>

                  <div className="mt-5">
                    <p className="mb-3 text-[14px] font-bold text-[#333438]">
                      Feedback History
                    </p>
                    <div className="overflow-hidden rounded-[8px] border border-[#E5E7EB]">
                      <table className="w-full border-collapse text-left">
                        <thead className="bg-[#e8cfd6]">
                          <tr>
                            {["Date", "Action", "Comments"].map((header) => (
                              <th
                                className="px-4 py-3 text-[12px] font-bold uppercase text-crimson-700"
                                key={header}
                              >
                                {header}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {feedback.length > 0 ? (
                            feedback.map((row, index) => (
                              <tr key={`${row.action}-${row.date}-${index}`}>
                                <td className="px-4 py-3 text-[13px] text-[#77777a]">
                                  {formatDate(row.date)}
                                </td>
                                <td className="px-4 py-3">
                                  <Badge tone={reviewStatusTone(row.action)}>{row.action}</Badge>
                                </td>
                                <td className="px-4 py-3 text-[13px] text-[#555b66]">
                                  {row.comments || "-"}
                                </td>
                              </tr>
                            ))
                          ) : (
                            <tr>
                              <td
                                className="px-4 py-5 text-center text-[13px] text-[#9ca0a8]"
                                colSpan={3}
                              >
                                No feedback recorded yet
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-wrap gap-3">
                    <Button
                      disabled={actionState.moving}
                      isLoading={actionState.saving}
                      leftIcon={<Save className="h-4 w-4" />}
                      onClick={() => save(match)}
                    >
                      Save Status
                    </Button>
                    <Button
                      disabled={actionState.saving}
                      isLoading={actionState.moving}
                      onClick={() => moveNext(match)}
                      rightIcon={<ArrowRight className="h-4 w-4" />}
                      variant="secondary"
                    >
                      Move to Next Stage
                    </Button>
                  </div>
                  {actionState.message ? (
                    <p
                      className={`mt-3 text-[13px] font-bold ${
                        actionState.messageTone === "success"
                          ? "text-[#04743b]"
                          : "text-[#b91c1c]"
                      }`}
                    >
                      {actionState.message}
                    </p>
                  ) : null}
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
                <Button
                  className="w-full"
                  onClick={() => setToast("Coming soon")}
                  variant="secondary"
                >
                  Export Report
                </Button>
                <Button
                  className="w-full"
                  onClick={() => setToast("Coming soon")}
                  variant="secondary"
                >
                  Send Reminders
                </Button>
                {selectedJobId ? (
                  <Link href={`/matches/${encodeURIComponent(selectedJobId)}`}>
                    <Button className="mt-2 w-full">View Final Selection</Button>
                  </Link>
                ) : null}
              </div>
              {toast ? (
                <p className="mt-3 text-center text-[13px] font-bold text-crimson-700">
                  {toast}
                </p>
              ) : null}
            </div>
          </Card>
        </div>
      )}

      {showInterviewModal && interviewResult ? (
        <InterviewResultsModal
          isRefreshing={isRefreshingInterview}
          isSaving={modalActionLoading}
          onClose={closeInterviewModal}
          onProceed={() => completeFromModal("Uplifted")}
          onRefresh={refreshInterviewResults}
          onReject={() => completeFromModal("Sent")}
          result={interviewResult}
        />
      ) : null}
    </>
  );
}

function InterviewResultsModal({
  isRefreshing,
  isSaving,
  onClose,
  onProceed,
  onRefresh,
  onReject,
  result,
}: {
  isRefreshing: boolean;
  isSaving: "uplift" | "reject" | null;
  onClose: () => void;
  onProceed: () => void;
  onRefresh: () => void;
  onReject: () => void;
  result: InterviewResult;
}) {
  const assessment = result.assessment;
  const responses = result.responses ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
      <div className="relative max-h-[88vh] w-full max-w-[920px] overflow-y-auto rounded-[8px] bg-white p-7 shadow-2xl">
        <button
          aria-label="Close interview results"
          className="absolute right-5 top-4 text-[28px] leading-none text-[#77777a] hover:text-[#333438]"
          onClick={onClose}
          type="button"
        >
          {"\u00d7"}
        </button>

        <div className="pr-10">
          <p className="text-[12px] font-bold uppercase tracking-[0.14em] text-crimson-700">
            Interview Results
          </p>
          <h2 className="mt-2 text-[26px] font-bold text-[#333438]">{result.candidate_name}</h2>
          <p className="mt-1 text-[15px] text-[#77777a]">{result.job_title}</p>
        </div>

        <div className="mt-6 space-y-6">
          {assessment ? (
            <div className="rounded-[8px] border border-[#E5E7EB] bg-[#f9fafb] p-5">
              <p className="text-[13px] font-bold uppercase text-[#77777a]">Overall Score</p>
              <p className={`mt-2 text-[44px] font-bold ${scoreTextColor(assessment.overall_interview_score)}`}>
                {assessment.overall_interview_score}/100
              </p>
              <p className="mt-3 text-[15px] leading-7 text-[#555b66]">{assessment.summary}</p>
            </div>
          ) : null}

          <section>
            <h3 className="mb-3 text-[18px] font-bold text-[#333438]">Q&A Transcript</h3>
            {responses.length > 0 ? (
              <div className="space-y-4">
                {responses.map((response) => {
                  const answerAssessment = assessment?.answer_assessments.find(
                    (item) => item.question_index === response.question_index,
                  );

                  return (
                    <div
                      className="relative rounded-[8px] border border-[#E5E7EB] p-4"
                      key={`${response.question_index}-${response.submitted_at}`}
                    >
                      {answerAssessment ? (
                        <Badge className="absolute right-4 top-4" tone={scoreTone(answerAssessment.score)}>
                          {answerAssessment.score}/100
                        </Badge>
                      ) : null}
                      <div className="rounded-[8px] bg-[#f3f4f6] p-3 pr-24 text-[14px] font-bold text-[#333438]">
                        {response.question}
                      </div>
                      <p className="mt-3 text-[14px] leading-6 text-[#555b66]">{response.transcript}</p>
                      {answerAssessment?.comment ? (
                        <p className="mt-3 text-[13px] italic text-[#77777a]">{answerAssessment.comment}</p>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-[8px] border border-[#E5E7EB] bg-[#f9fafb] p-5 text-[14px] text-[#77777a]">
                No interview responses recorded yet.
              </div>
            )}
          </section>

          {result.video_analysis ? (
            <section className="rounded-[8px] border border-[#E5E7EB] p-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-[18px] font-bold text-[#333438]">Presentation Analysis</h3>
                <Badge tone={scoreTone(result.video_analysis.confidence_score)}>
                  {result.video_analysis.confidence_score}/100
                </Badge>
              </div>
              <div className="space-y-3">
                {[
                  ["Eye Contact", result.video_analysis.eye_contact],
                  ["Presentation", result.video_analysis.presentation],
                  ["Body Language", result.video_analysis.body_language],
                  ["Communication", result.video_analysis.communication_clarity],
                  ["Engagement", result.video_analysis.engagement_over_time],
                ].map(([label, value]) => (
                  <div className="rounded-[8px] bg-[#f9fafb] px-4 py-3" key={label}>
                    <p className="text-[13px] font-bold text-[#333438]">{label}</p>
                    <p className="mt-1 text-[14px] leading-6 text-[#555b66]">{value}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {!assessment ? (
            <div className="rounded-[8px] border border-[#f7d06b] bg-[#fffbeb] p-4 text-[14px] font-bold text-[#a65f00]">
              AI scoring is being processed. Raw transcript is shown above.
              <button
                className="ml-2 underline hover:text-[#7c4a00]"
                onClick={onRefresh}
                type="button"
              >
                Refresh to check scores
              </button>
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              <ResultList title="Key Observations" items={assessment.key_observations ?? []} />
              <ResultList title="Areas to Probe" items={assessment.areas_to_probe ?? []} />
            </div>
          )}
        </div>

        <div className="mt-7 flex flex-wrap items-center justify-end gap-3 border-t border-[#E5E7EB] pt-5">
          <Button
            className="mr-auto border-[#d8dee7] text-[#555b66] hover:bg-[#f9fafb]"
            isLoading={isRefreshing}
            onClick={onRefresh}
            size="sm"
            variant="secondary"
          >
            {"\u21bb"} Refresh Results
          </Button>
          <Button isLoading={isSaving === "uplift"} onClick={onProceed}>
            Proceed to Next Stage
          </Button>
          <Button isLoading={isSaving === "reject"} onClick={onReject} variant="danger">
            Reject
          </Button>
        </div>
      </div>
    </div>
  );
}

function ResultList({ items, title }: { items: string[]; title: string }) {
  return (
    <section className="rounded-[8px] border border-[#E5E7EB] p-4">
      <h3 className="mb-3 text-[16px] font-bold text-[#333438]">{title}</h3>
      {items.length > 0 ? (
        <ul className="space-y-2 text-[14px] leading-6 text-[#555b66]">
          {items.map((item) => (
            <li key={item}>• {item}</li>
          ))}
        </ul>
      ) : (
        <p className="text-[14px] text-[#9ca0a8]">No items recorded.</p>
      )}
    </section>
  );
}

function reviewStatusTone(
  status?: string,
): "green" | "blue" | "indigo" | "purple" | "amber" | "red" | "grey" | "crimson" {
  switch ((status ?? "Matched").toLowerCase()) {
    case "matched":
    case "interview sent":
      return "blue";
    case "approved":
      return "indigo";
    case "shortlisted":
      return "purple";
    case "interview completed":
    case "assessed":
      return "green";
    case "uplifted":
      return "amber";
    case "sent":
      return "grey";
    default:
      return "grey";
  }
}

function scoreTone(score: number): "green" | "amber" | "red" {
  if (score >= 80) {
    return "green";
  }

  if (score >= 60) {
    return "amber";
  }

  return "red";
}

function scoreTextColor(score: number) {
  if (score >= 80) {
    return "text-[#00a64f]";
  }

  if (score >= 60) {
    return "text-[#d18b00]";
  }

  return "text-[#dc2626]";
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
    <div
      className={`mb-4 rounded-[8px] border px-4 py-4 ${
        tone === "green"
          ? "border-[#b7efc9] bg-[#effbf3] text-[#04743b]"
          : tone === "red"
            ? "border-[#fecaca] bg-[#fff1f1] text-[#b91c1c]"
            : tone === "amber"
              ? "border-[#fde68a] bg-[#fffbea] text-[#a65f00]"
              : "border-[#E5E7EB] bg-white text-[#333438]"
      }`}
    >
      <p className="text-[14px]">{label}</p>
      <p className="mt-3 text-[26px] font-bold">{value}</p>
    </div>
  );
}