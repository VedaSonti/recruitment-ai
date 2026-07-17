import type { Candidate, Job, Match } from "@/src/lib/api";

export function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function getJobId(job: Job) {
  return job.job_id ?? job._id ?? job.id ?? "";
}

export function getCandidateId(candidate: Candidate) {
  return candidate.candidate_id ?? candidate._id ?? candidate.id ?? "";
}

export function getMatchId(match: Match) {
  return match.match_id ?? match._id ?? match.id ?? "";
}

export function getJobTitle(job?: Job | null) {
  return job?.title ?? job?.job_title ?? "Untitled Job";
}

export function getClient(job?: Job | null) {
  return job?.client_name || job?.client || job?.domain || "-";
}

export function formatDate(value?: string | Date | null) {
  if (!value) {
    return "-";
  }

  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toISOString().slice(0, 10);
}

export function scoreToPercent(score?: number | null) {
  const value = score ?? 0;
  return Math.round(value > 1 ? value : value * 100);
}

export function initials(name?: string | null) {
  return (name || "?")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function fileSize(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function isDuplicateUpload(error: unknown) {
  return (
    error instanceof Error &&
    error.message.toLowerCase().includes("already been uploaded")
  );
}
