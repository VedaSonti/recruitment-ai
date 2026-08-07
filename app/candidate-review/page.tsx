"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
  prepareProfileUplift,
  scheduleInterview,
  updateMatchStatus,
  type Job,
  type Match,
  type MatchStatus,
  type HeadOrientationObservation,
  type SpeakerObservation,
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
type InterviewResult = Awaited<ReturnType<typeof getInterviewByMatch>>;

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

function resolveMediaUrl(url?: string | null) {
  if (!url) {
    return null;
  }

  if (/^https?:\/\//i.test(url)) {
    return url;
  }

  return `${API_BASE_URL}${url.startsWith("/") ? url : `/${url}`}`;
}

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
  const router = useRouter();
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
  const [showProceedConfirmation, setShowProceedConfirmation] = useState(false);
  const [proceedError, setProceedError] = useState("");
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

  async function rejectFromModal() {
    if (!activeInterviewMatchId) {
      return;
    }

    setModalActionLoading("reject");

    try {
      await updateMatchStatus(activeInterviewMatchId, "Sent");
      patchMatch(activeInterviewMatchId, {
        status: "Sent",
        updated_at: new Date().toISOString(),
      });
      await closeInterviewModal();
    } finally {
      setModalActionLoading(null);
    }
  }

  async function confirmProceedToUplift() {
    if (!activeInterviewMatchId || modalActionLoading === "uplift") {
      return;
    }

    setModalActionLoading("uplift");
    setProceedError("");
    try {
      const profile = await prepareProfileUplift(activeInterviewMatchId);
      patchMatch(activeInterviewMatchId, {
        status: "Uplifted",
        updated_at: new Date().toISOString(),
      });
      setShowProceedConfirmation(false);
      setShowInterviewModal(false);
      router.push(`/uplift?matchId=${encodeURIComponent(profile.match_id)}`);
    } catch (error) {
      setProceedError(error instanceof Error ? error.message : "Could not prepare the candidate profile.");
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
          onProceed={() => {
            setProceedError("");
            setShowProceedConfirmation(true);
          }}
          onRefresh={refreshInterviewResults}
          onReject={rejectFromModal}
          result={interviewResult}
        />
      ) : null}

      {showProceedConfirmation ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/45 p-6">
          <div className="w-full max-w-[520px] rounded-[10px] bg-white p-7 shadow-2xl">
            <p className="text-[12px] font-bold uppercase tracking-[0.12em] text-crimson-700">
              Recruiter confirmation
            </p>
            <h2 className="mt-2 text-[23px] font-bold text-[#333438]">
              Proceed with this candidate and prepare an iSOFT-formatted profile?
            </h2>
            <p className="mt-3 text-[14px] leading-6 text-[#667085]">
              This records your manual decision and creates one draft profile from verified CV information. It does not send anything to a client.
            </p>
            {proceedError ? (
              <p className="mt-4 rounded-[8px] border border-red-200 bg-red-50 p-3 text-[14px] text-red-700">
                {proceedError}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end gap-3">
              <Button
                disabled={modalActionLoading === "uplift"}
                onClick={() => setShowProceedConfirmation(false)}
                variant="secondary"
              >
                Cancel
              </Button>
              <Button
                isLoading={modalActionLoading === "uplift"}
                onClick={confirmProceedToUplift}
              >
                Proceed and Prepare Profile
              </Button>
            </div>
          </div>
        </div>
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
  const profileScore = result.profile_match_score;
  const interviewScore = assessment?.overall_interview_score ?? null;
  const combinedScore =
    typeof profileScore === "number" && typeof interviewScore === "number"
      ? Math.round(profileScore * 0.6 + interviewScore * 0.4)
      : null;
  const videoStatus = result.video_analysis_status ?? result.video_analysis?.video_analysis_status ?? "pending";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
      <div className="relative max-h-[88vh] w-full max-w-[980px] overflow-y-auto rounded-[8px] bg-white p-7 shadow-2xl">
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
          <section className="grid gap-4 md:grid-cols-3">
            <ScoreSummaryCard
              caption="Original semantic profile similarity."
              label="Profile Match"
              score={profileScore}
            />
            <ScoreSummaryCard
              caption="Answer quality based on question responses."
              label="Interview Answer Assessment"
              score={interviewScore}
            />
            <ScoreSummaryCard
              caption="Display-only blend: 60% profile, 40% interview. Video observations are excluded."
              label="Combined Profile/Interview"
              score={combinedScore}
            />
          </section>

          {assessment ? (
            <section className="rounded-[8px] border border-[#E5E7EB] bg-[#f9fafb] p-5">
              <p className="text-[13px] font-bold uppercase text-[#77777a]">Interview Answer Assessment</p>
              <p className="mt-3 text-[15px] leading-7 text-[#555b66]">{assessment.summary}</p>
            </section>
          ) : null}

          <section>
            <h3 className="mb-3 text-[18px] font-bold text-[#333438]">Questions, Transcripts, and Feedback</h3>
            {responses.length > 0 ? (
              <div className="space-y-4">
                {responses.map((response) => {
                  const answerAssessment = assessment?.answer_assessments.find(
                    (item) => item.question_index === response.question_index,
                  );
                  const responseVideo = response.video_observations;

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
                      <p className="mt-3 text-[14px] leading-6 text-[#555b66]">
                        {response.transcript || <span className="italic text-[#9ca0a8]">No transcript recorded.</span>}
                      </p>
                      {answerAssessment?.comment ? (
                        <p className="mt-3 text-[13px] italic text-[#77777a]">{answerAssessment.comment}</p>
                      ) : null}
                      {response.video_url ? (
                        <video
                          className="mt-4 w-full rounded-[8px] border border-[#E5E7EB]"
                          controls
                          id={`response-video-${response.question_index}`}
                          src={resolveMediaUrl(response.video_url) ?? undefined}
                        />
                      ) : response.video_playback_status === "historical_unavailable" ? (
                        <p className="mt-4 rounded-[8px] border border-[#E5E7EB] bg-[#f9fafb] p-3 text-[13px] text-[#77777a]">
                          Video playback is unavailable for this historical response because it was
                          recorded before persistent video storage was enabled. The deleted temporary
                          recording cannot be recovered.
                        </p>
                      ) : response.video_playback_status === "missing" ? (
                        <p className="mt-4 rounded-[8px] border border-[#f7d06b] bg-[#fffbeb] p-3 text-[13px] text-[#a65f00]">
                          This response was recorded, but its stored video file is missing. The
                          transcript remains available.
                        </p>
                      ) : null}
                      {responseVideo ? (
                        <div className="mt-4 rounded-[8px] bg-[#f9fafb] p-3">
                          <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-[#77777a]">
                            Per-Response Video Observations
                          </p>
                          <div className="mt-3 grid gap-2 text-[13px] text-[#555b66] sm:grid-cols-3">
                            <ObservationMetric label="Visible" value={formatMaybePercent(responseVideo.face_visible_percentage)} />
                            <ObservationMetric label="Filler words" value={formatMaybeValue(responseVideo.filler_word_count)} />
                            <ObservationMetric label="Long pauses" value={formatMaybeValue(responseVideo.long_pause_count)} />
                          </div>
                          {responseVideo.notes?.length ? (
                            <ul className="mt-3 space-y-1 text-[13px] leading-5 text-[#555b66]">
                              {responseVideo.notes.map((note) => (
                                <li key={note}>- {note}</li>
                              ))}
                            </ul>
                          ) : null}
                        </div>
                      ) : null}
                      {responseVideo?.head_orientation || responseVideo?.speaker_observations ? (
                        <RecordingObservationsCard
                          head={responseVideo.head_orientation}
                          questionIndex={response.question_index}
                          speaker={responseVideo.speaker_observations}
                        />
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

          <VideoObservationsSection analysis={result.video_analysis} status={videoStatus} />

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

        <div className="mt-7 border-t border-[#E5E7EB] pt-5">
          <div className="mb-4 rounded-[8px] bg-[#f9fafb] p-4">
            <p className="text-[13px] font-bold uppercase tracking-[0.1em] text-[#77777a]">Recruiter Decision</p>
            <p className="mt-2 text-[14px] leading-6 text-[#555b66]">
              Video observations are assistive context only. Proceeding or rejecting remains a manual recruiter action.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
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
    </div>
  );
}

function ScoreSummaryCard({ caption, label, score }: { caption: string; label: string; score: number | null }) {
  return (
    <div className="rounded-[8px] border border-[#E5E7EB] bg-white p-4">
      <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-[#77777a]">{label}</p>
      <p className={`mt-3 text-[32px] font-bold ${typeof score === "number" ? scoreTextColor(score) : "text-[#77777a]"}`}>
        {typeof score === "number" ? `${score}/100` : "Pending"}
      </p>
      <p className="mt-2 text-[13px] leading-5 text-[#77777a]">{caption}</p>
    </div>
  );
}

function VideoObservationsSection({
  analysis,
  status,
}: {
  analysis: InterviewResult["video_analysis"];
  status: InterviewResult["video_analysis_status"];
}) {
  const observations = analysis?.video_observations;
  const quality = observations?.recording_quality;
  const delivery = observations?.delivery_observations;
  const environment = observations?.environment_observations;
  const processing = status === "pending" || status === "processing";

  return (
    <section className="rounded-[8px] border border-[#E5E7EB] p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-[18px] font-bold text-[#333438]">Video Observations</h3>
          <p className="mt-2 max-w-3xl rounded-[8px] border border-[#d8dee7] bg-[#f9fafb] p-3 text-[13px] leading-5 text-[#555b66]">
            Video observations describe recording and presentation signals only. They do not determine honesty,
            personality, emotional state, or candidate suitability. The recruiter must make the final decision.
          </p>
        </div>
        <Badge tone={videoStatusTone(status)}>{statusLabel(status)}</Badge>
      </div>

      {processing ? (
        <div className="rounded-[8px] border border-[#f7d06b] bg-[#fffbeb] p-4 text-[14px] font-bold text-[#a65f00]">
          Video observations are still being processed.
        </div>
      ) : observations ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <ObservationMetric label="Recording availability" value={quality?.video_available ? "Video available" : "Video unavailable"} />
            <ObservationMetric label="Audio availability" value={quality?.audio_available ? "Audio available" : "Audio unavailable"} />
            <ObservationMetric label="Candidate visible" value={formatMaybePercent(quality?.face_visible_percentage)} />
            <ObservationMetric label="Multiple faces" value={formatBoolean(quality?.multiple_faces_detected)} />
            <ObservationMetric label="Lighting" value={quality?.lighting ?? "unknown"} />
            <ObservationMetric label="Framing" value={quality?.framing ?? "unknown"} />
            <ObservationMetric label="Audio clarity" value={quality?.audio_clarity ?? "unknown"} />
            <ObservationMetric label="Background noise" value={quality?.background_noise ?? "unknown"} />
            <ObservationMetric label="Speaking time" value={formatSeconds(delivery?.speaking_time_seconds)} />
            <ObservationMetric label="Speech-rate estimate" value={formatWpm(delivery?.estimated_words_per_minute)} />
            <ObservationMetric label="Filler-word count" value={formatMaybeValue(delivery?.filler_word_count)} />
            <ObservationMetric label="Long-pause count" value={formatMaybeValue(delivery?.long_pause_count)} />
            <ObservationMetric label="Within 30 seconds" value={formatBoolean(delivery?.response_completed_within_limit)} />
            <ObservationMetric label="Mainly toward screen" value={formatMaybePercent(delivery?.screen_direction_percentage)} />
          </div>

          {observations.neutral_summary ? (
            <div className="rounded-[8px] bg-[#f9fafb] px-4 py-3">
              <p className="text-[13px] font-bold text-[#333438]">Neutral Summary</p>
              <p className="mt-1 text-[14px] leading-6 text-[#555b66]">{observations.neutral_summary}</p>
            </div>
          ) : null}

          <ResultList title="Technical and Delivery Observations" items={observations.technical_observations ?? []} />

          {environment ? (
            <div className="rounded-[8px] border border-[#E5E7EB] bg-white p-4">
              <h4 className="text-[16px] font-bold text-[#333438]">Interview Environment Observations</h4>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <ObservationMetric label="Clear-face coverage" value={formatMaybePercent(environment.face_detection_coverage_percent)} />
                <ObservationMetric label="Sustained downward responses" value={String(environment.responses_with_sustained_downward_orientation)} />
                <ObservationMetric label="Possible additional voice" value={`${environment.responses_with_possible_additional_speaker} responses`} />
                <ObservationMetric label="Possible overlap" value={formatSeconds(environment.overlapping_speech_seconds)} />
              </div>
              <p className="mt-3 text-[14px] leading-6 text-[#555b66]">{environment.neutral_summary}</p>
              <p className="mt-3 rounded-[8px] bg-[#F2E1E3] p-3 text-[13px] leading-5 text-[#5C0D1B]">
                {environment.assistive_context_notice}
              </p>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="rounded-[8px] border border-[#E5E7EB] bg-[#f9fafb] p-4 text-[14px] text-[#77777a]">
          Video observations are not available for this interview.
        </div>
      )}
    </section>
  );
}

function ObservationMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[8px] bg-[#f9fafb] px-4 py-3">
      <p className="text-[12px] font-bold uppercase tracking-[0.06em] text-[#77777a]">{label}</p>
      <p className="mt-1 text-[14px] font-semibold text-[#333438]">{value}</p>
    </div>
  );
}

function formatMaybeValue(value?: number | null) {
  return typeof value === "number" ? String(value) : "unknown";
}

function formatMaybePercent(value?: number | null) {
  return typeof value === "number" ? `${value}%` : "unknown";
}

function formatSeconds(value?: number | null) {
  return typeof value === "number" ? `${value}s` : "unknown";
}

function formatWpm(value?: number | null) {
  return typeof value === "number" ? `${value} wpm` : "unknown";
}

function formatBoolean(value?: boolean | null) {
  if (value === true) {
    return "Yes";
  }
  if (value === false) {
    return "No";
  }
  return "unknown";
}

function statusLabel(status: string) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function videoStatusTone(status: string): "green" | "amber" | "red" | "grey" | "blue" {
  switch (status) {
    case "completed":
      return "green";
    case "processing":
    case "pending":
      return "amber";
    case "failed":
      return "red";
    case "unavailable":
      return "grey";
    default:
      return "blue";
  }
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

function RecordingObservationsCard({
  head,
  questionIndex,
  speaker,
}: {
  head?: HeadOrientationObservation;
  questionIndex: number;
  speaker?: SpeakerObservation;
}) {
  return (
    <div className="mt-4 rounded-[8px] border border-[#E5E7EB] bg-white p-4">
      <p className="text-[13px] font-bold uppercase tracking-[0.08em] text-[#5C0D1B]">
        Presentation and Recording Observations
      </p>
      <p className="mt-2 text-[12px] leading-5 text-[#77777a]">
        Review the recording above before interpreting any timestamped observation.
      </p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div>
          <p className="text-[14px] font-bold text-[#333438]">Head orientation</p>
          {head?.status === "completed" ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <ObservationMetric label="Candidate visible" value={head.candidate_visible === "true" ? "Yes" : head.candidate_visible === "false" ? "No" : "Unknown"} />
              <ObservationMetric label="Clear-face coverage" value={formatMaybePercent(head.face_detection_coverage_percent)} />
              <ObservationMetric label="Mainly toward screen" value={capitalize(head.mainly_toward_screen)} />
              <ObservationMetric label="Downward orientation" value={formatMaybePercent(head.downward_percent_of_valid_frames)} />
              <ObservationMetric label="Longest downward interval" value={formatSeconds(head.longest_downward_interval_seconds)} />
              <ObservationMetric label="Rapid movements" value={String(head.rapid_movement_count)} />
              <ObservationMetric label="Candidate outside frame" value={head.candidate_left_frame ? formatSeconds(head.longest_face_absent_interval_seconds) : "Not sustained"} />
              <ObservationMetric label="Multiple faces" value={formatBoolean(head.multiple_faces_detected)} />
            </div>
          ) : (
            <ObservationStatusMessage reason={head?.status_reason ?? "Head-orientation analysis is pending."} />
          )}
          {head?.head_observation_intervals?.length ? (
            <ObservationTimestampList
              intervals={head.head_observation_intervals.map((interval) => ({
                ...interval,
                label: interval.type === "face_absent" ? "Review face-absent interval" : "Review downward-orientation interval",
              }))}
              questionIndex={questionIndex}
            />
          ) : null}
          {head?.rapid_movement_events?.length ? (
            <ObservationTimestampList
              intervals={head.rapid_movement_events.map((event) => ({
                start_seconds: event.time_seconds,
                end_seconds: event.time_seconds,
                label: `Review ${event.movement_type} movement`,
              }))}
              questionIndex={questionIndex}
            />
          ) : null}
        </div>

        <div>
          <p className="text-[14px] font-bold text-[#333438]">Audio speakers</p>
          {speaker?.status === "completed" ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <ObservationMetric label="Candidate speech" value={speaker.candidate_speech_detected ? "Detected" : "Not detected"} />
              <ObservationMetric label="Estimated speakers" value={speaker.estimated_speaker_count === null ? "Insufficient evidence" : String(speaker.estimated_speaker_count)} />
              <ObservationMetric label="Possible additional speaker" value={speaker.possible_additional_speaker ? "Possible—review recording" : "Not indicated"} />
              <ObservationMetric label="Possible overlapping speech" value={speaker.overlapping_speech_detected ? formatSeconds(speaker.overlapping_speech_seconds) : "Not indicated"} />
              <ObservationMetric label="Confidence" value={formatConfidence(speaker.speaker_analysis_confidence)} />
            </div>
          ) : (
            <ObservationStatusMessage reason={speaker?.status_reason ?? "Speaker analysis is pending."} />
          )}
          {speaker?.possible_second_speaker_intervals?.length ? (
            <ObservationTimestampList
              intervals={speaker.possible_second_speaker_intervals.map((interval) => ({
                ...interval,
                label: `Review possible additional speaker (${interval.speaker_label})`,
              }))}
              questionIndex={questionIndex}
            />
          ) : null}
          {speaker?.overlapping_speech_intervals?.length ? (
            <ObservationTimestampList
              intervals={speaker.overlapping_speech_intervals.map((interval) => ({
                ...interval,
                label: "Review overlapping speech",
              }))}
              questionIndex={questionIndex}
            />
          ) : null}
        </div>
      </div>
      <p className="mt-4 rounded-[8px] bg-[#f9fafb] p-3 text-[12px] leading-5 text-[#77777a]">
        Head orientation may vary because of camera placement, reading, notes, a keyboard, another monitor, lighting, glasses, partial visibility, or mobility. These measurements do not establish attention, assistance, or intent.
      </p>
    </div>
  );
}

function ObservationTimestampList({
  intervals,
  questionIndex,
}: {
  intervals: Array<{ start_seconds: number; end_seconds: number; label: string }>;
  questionIndex: number;
}) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {intervals.map((interval, index) => (
        <button
          className="rounded-full border border-[#d8dee7] bg-white px-3 py-1.5 text-[12px] font-semibold text-[#5C0D1B] hover:bg-[#F2E1E3]"
          key={`${interval.label}-${interval.start_seconds}-${index}`}
          onClick={() => seekToObservation(questionIndex, interval.start_seconds)}
          type="button"
        >
          {interval.label}: {formatSeconds(interval.start_seconds)}
          {interval.end_seconds > interval.start_seconds ? `–${formatSeconds(interval.end_seconds)}` : ""}
        </button>
      ))}
    </div>
  );
}

function seekToObservation(questionIndex: number, seconds: number) {
  const video = document.getElementById(`response-video-${questionIndex}`) as HTMLVideoElement | null;
  if (!video) return;
  video.currentTime = Math.max(0, seconds);
  video.scrollIntoView({ behavior: "smooth", block: "center" });
  video.focus();
}

function ObservationStatusMessage({ reason }: { reason: string }) {
  return <p className="mt-3 rounded-[8px] bg-[#f9fafb] p-3 text-[13px] leading-5 text-[#77777a]">{reason}</p>;
}

function capitalize(value: string) {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "Unknown";
}

function formatConfidence(value: number) {
  const label = value >= 0.75 ? "High" : value >= 0.5 ? "Moderate" : "Low";
  return `${label} (${Math.round(value * 100)}%)`;
}
