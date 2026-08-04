const rawBaseUrl = process.env.NEXT_PUBLIC_API_URL;

if (!rawBaseUrl) {
  throw new Error("NEXT_PUBLIC_API_URL is not configured.");
}

const API_BASE_URL = rawBaseUrl.replace(/\/+$/, "");

export type MatchStatus =
  | "Uploaded"
  | "Matched"
  | "Approved"
  | "Shortlisted"
  | "Interview Sent"
  | "Interview Completed"
  | "Uplifted"
  | "Sent";

export interface Job {
  id?: string;
  _id?: string;
  job_id?: string;
  title?: string;
  job_title?: string;
  domain?: string;
  client?: string;
  client_name?: string;
  source_file?: string;
  location?: string;
  status?: string;
  budget?: string;
  salary_range?: string;
  experience_required?: string;
  min_years_experience?: number;
  skills?: string[];
  required_skills?: string[];
  nice_to_have_skills?: string[];
  domain_experience?: string[];
  summary?: string;
  description?: string;
  description_raw?: string;
  responsibilities?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface WorkExperience {
  title?: string;
  company?: string;
  start_year?: string | number;
  end_year?: string | number;
  is_current?: boolean;
  highlights?: string[];
}

export interface Education {
  degree?: string;
  institution?: string;
  year?: string | number;
}

export interface Candidate {
  id?: string;
  _id?: string;
  candidate_id?: string;
  name?: string;
  email?: string;
  phone?: string;
  title?: string;
  current_title?: string;
  source_file?: string;
  location?: string;
  skills?: string[];
  domain_experience?: string[];
  years_experience?: number | string;
  work_rights?: string;
  notice_period?: string;
  expected_salary?: string;
  summary?: string;
  status?: string;
  work_experience?: WorkExperience[];
  education?: Education[];
  key_achievements?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface DecisionAnalysis {
  ai_summary?: string;
  strengths?: string[];
  risks?: string[];
  tech_match_percentage?: number;
  exp_match_percentage?: number;
  education_match_percentage?: number;
  matched_skills?: string[];
  missing_skills?: string[];
  interview_questions?: string[];
}

export interface SkillMatch {
  required: string;
  matched_with?: string;
  closest_match?: string;
  similarity: number;
  type: "strong" | "partial" | "missing";
  match_reason?:
    | "exact_normalized"
    | "category_alias"
    | "embedding_similarity"
    | "no_candidate_skills"
    | "no_match";
}

export interface SkillAnalysis {
  match_id: string;
  semantic_skill_score: number;
  matched: SkillMatch[];
  partial: SkillMatch[];
  missing: SkillMatch[];
  summary: string;
}

export interface Match {
  id?: string;
  _id?: string;
  match_id?: string;
  job_id?: string;
  candidate_id?: string;
  job?: Job;
  candidate?: Candidate;
  job_title?: string;
  job_domain?: string;
  candidate_name?: string;
  candidate_email?: string | null;
  match_score?: number;
  score?: number;
  status?: MatchStatus | string;
  status_note?: string;
  analysis?: DecisionAnalysis | null;
  skill_analysis?: SkillAnalysis | null;
  analysis_generated_at?: string;
  created_at?: string;
  updated_at?: string;
}

export interface APIError {
  status: number;
  message: string;
  error?: string;
  details?: unknown;
}

export interface UploadResponse {
  message: string;
  job_ids?: string[];
  candidate_id?: string;
  matched_against_existing_candidates?: number | boolean;
  matched_against_existing_jobs?: number | boolean;
}

export interface TopCandidateAnalysisResult {
  job_id: string;
  analysed: Array<{ match_id: string; analysis: DecisionAnalysis }>;
}

export interface UpliftExperience {
  title?: string;
  company?: string;
  start_year?: string | number;
  end_year?: string | number;
  is_current?: boolean;
  highlights?: string[];
}

export interface UpliftProfileContent {
  name: string;
  professional_title: string;
  professional_summary: string;
  core_skills: string[];
  technical_skills: string[];
  professional_experience: UpliftExperience[];
  key_achievements: string[];
  education: Education[];
  certifications: string[];
  contact: { email?: string; phone?: string; location?: string };
  additional_information: { work_rights?: string; notice_period?: string };
  section_visibility: Record<string, boolean>;
}

export interface UpliftProfile {
  profile_id: string;
  candidate_id: string;
  match_id: string;
  job_id: string;
  interview_id?: string | null;
  candidate_name: string;
  target_job: string;
  workflow_status: string;
  uplift_status: "Ready" | "Draft" | "Generated" | "Delivered" | string;
  profile_match_score?: number | null;
  interview_score?: number | null;
  combined_score?: number | null;
  original_cv_reference: {
    source_file?: string | null;
    available: boolean;
    download_url?: string | null;
  };
  uplifted_profile: UpliftProfileContent;
  generated_file_reference?: string | null;
  download_url?: string | null;
  verified_by_recruiter_at?: string | null;
  created_at?: string;
  updated_at?: string;
  generated_at?: string | null;
}

export class RecruitmentAPIError extends Error implements APIError {
  status: number;
  error?: string;
  details?: unknown;

  constructor(apiError: APIError) {
    super(apiError.message);
    this.name = "RecruitmentAPIError";
    this.status = apiError.status;
    this.error = apiError.error;
    this.details = apiError.details;
    Object.setPrototypeOf(this, RecruitmentAPIError.prototype);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function buildUrl(path: string) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

async function parseResponse(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";

  if (response.status === 204) {
    return undefined;
  }

  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  return text || undefined;
}

function toAPIError(response: Response, body: unknown): APIError {
  const fallbackMessage = `Request failed with status ${response.status}`;

  if (isRecord(body)) {
    const message =
      typeof body.message === "string"
        ? body.message
        : typeof body.detail === "string"
          ? body.detail
          : fallbackMessage;

    return {
      status: response.status,
      message,
      error:
        typeof body.error === "string"
          ? body.error
          : typeof body.code === "string"
            ? body.code
            : undefined,
      details: body.details ?? body.detail ?? body,
    };
  }

  return {
    status: response.status,
    message: typeof body === "string" && body ? body : fallbackMessage,
  };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const isFormData = options.body instanceof FormData;

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  if (options.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(buildUrl(path), {
    ...options,
    headers,
    cache: "no-store",
  });
  const body = await parseResponse(response);

  if (!response.ok) {
    throw new RecruitmentAPIError(toAPIError(response, body));
  }

  return body as T;
}

function unwrapList<T>(body: unknown, key: string): T[] {
  if (Array.isArray(body)) {
    return body as T[];
  }

  if (isRecord(body) && Array.isArray(body[key])) {
    return body[key] as T[];
  }

  return [];
}

export function isAPIError(error: unknown): error is RecruitmentAPIError {
  return error instanceof RecruitmentAPIError;
}

export async function getJobs(status?: string): Promise<Job[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const response = await request<Job[] | { total: number; jobs: Job[] }>(
    `/jobs${query}`,
    { method: "GET" },
  );
  return unwrapList<Job>(response, "jobs");
}

export async function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`, { method: "GET" });
}

export async function uploadJob(
  file: File,
  details?: {
    clientName?: string;
    location?: string;
    salaryRange?: string;
    experienceRequired?: string;
  },
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  if (details?.clientName) {
    formData.append("client_name", details.clientName);
  }
  if (details?.location) {
    formData.append("location", details.location);
  }
  if (details?.salaryRange) {
    formData.append("salary_range", details.salaryRange);
  }
  if (details?.experienceRequired) {
    formData.append("experience_required", details.experienceRequired);
  }

  return request<UploadResponse>("/jobs/upload", {
    method: "POST",
    body: formData,
  });
}

export async function getCandidates(): Promise<Candidate[]> {
  const response = await request<
    Candidate[] | { total: number; candidates: Candidate[] }
  >("/candidates", { method: "GET" });
  return unwrapList<Candidate>(response, "candidates");
}

export async function getCandidate(id: string): Promise<Candidate> {
  return request<Candidate>(`/candidates/${encodeURIComponent(id)}`, {
    method: "GET",
  });
}

export async function uploadCandidate(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  return request<UploadResponse>("/candidates/upload", {
    method: "POST",
    body: formData,
  });
}

export async function getMatch(matchId: string): Promise<Match> {
  return request<Match>(`/matches/${encodeURIComponent(matchId)}`, {
    method: "GET",
  });
}

export async function getMatchesByJob(jobId: string): Promise<Match[]> {
  try {
    const response = await request<{ job_id: string; ranked_candidates: Match[] }>(
      `/matches/by-job/${encodeURIComponent(jobId)}`,
      { method: "GET" },
    );
    return response.ranked_candidates ?? [];
  } catch (error) {
    if (isAPIError(error) && error.status === 404) {
      return [];
    }
    throw error;
  }
}

export async function getMatchesByCandidate(
  candidateId: string,
): Promise<Match[]> {
  try {
    const response = await request<{ candidate_id: string; ranked_jobs: Match[] }>(
      `/matches/by-candidate/${encodeURIComponent(candidateId)}`,
      { method: "GET" },
    );
    return response.ranked_jobs ?? [];
  } catch (error) {
    if (isAPIError(error) && error.status === 404) {
      return [];
    }
    throw error;
  }
}

export function updateMatchStatus(
  matchId: string,
  status: MatchStatus,
  note = "",
): Promise<Match> {
  return request<Match>(`/matches/${encodeURIComponent(matchId)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status, status_note: note }),
  });
}

export async function analyseMatch(matchId: string): Promise<{
  match_id: string;
  analysis: DecisionAnalysis;
}> {
  return request(`/matches/${encodeURIComponent(matchId)}/analyse`, {
    method: "POST",
  });
}

export async function analyseTopCandidates(
  jobId: string,
  limit = 5,
): Promise<TopCandidateAnalysisResult> {
  const matches = (await getMatchesByJob(jobId)).slice(0, limit);
  const analysed = [];

  for (const match of matches) {
    if (match.analysis && match.match_id) {
      analysed.push({ match_id: match.match_id, analysis: match.analysis });
      continue;
    }

    if (match.match_id) {
      analysed.push(await analyseMatch(match.match_id));
    }
  }

  return { job_id: jobId, analysed };
}

export async function getSkillAnalysis(
  matchId: string,
): Promise<SkillAnalysis> {
  return request(`/matches/${encodeURIComponent(matchId)}/skill-analysis`, {
    method: "GET",
  });
}

export async function scheduleInterview(matchId: string): Promise<{
  message: string;
  token: string;
  interview_url: string;
  candidate_email: string;
  expires_at: string;
  email_sent: boolean;
}> {
  return request(`/interviews/schedule/${encodeURIComponent(matchId)}`, {
    method: "POST",
  });
}

export async function getInterviewByMatch(matchId: string): Promise<{
  interview_id: string;
  candidate_name: string;
  candidate_email: string;
  job_title: string;
  status: string;
  profile_match_score: number | null;
  questions: string[];
  responses: Array<{
    question_index: number;
    question: string;
    transcript: string;
    submitted_at: string;
    video_url?: string | null;
    video_available?: boolean;
    video_playback_status?: "available" | "missing" | "historical_unavailable" | "not_recorded";
    video_size_bytes?: number | null;
    video_duration_seconds?: number | null;
    video_content_type?: string | null;
    video_observations?: {
      face_visible_percentage: number | null;
      speaking_time_seconds: number | null;
      filler_word_count: number | null;
      long_pause_count: number | null;
      longest_pause_seconds?: number | null;
      response_completed_within_limit: boolean | null;
      screen_direction_percentage?: number | null;
      notes: string[];
    } | null;
  }>;
  assessment: {
    overall_interview_score: number;
    summary: string;
    answer_assessments: Array<{
      question_index: number;
      question: string;
      score: number;
      comment: string;
    }>;
    key_observations: string[];
    areas_to_probe: string[];
  } | null;
  video_analysis_status: "pending" | "processing" | "completed" | "failed" | "unavailable";
  video_analysis: {
    video_analysis_status: "pending" | "processing" | "completed" | "failed" | "unavailable";
    video_observations: {
      recording_quality: {
        video_available: boolean;
        audio_available: boolean;
        face_visible_percentage: number | null;
        multiple_faces_detected: boolean | null;
        lighting: "good" | "acceptable" | "poor" | "unknown";
        framing: "good" | "acceptable" | "poor" | "unknown";
        audio_clarity: "good" | "acceptable" | "poor" | "unknown";
        background_noise: "low" | "moderate" | "high" | "unknown";
      };
      delivery_observations: {
        speaking_time_seconds: number | null;
        estimated_words_per_minute: number | null;
        filler_word_count: number | null;
        long_pause_count: number | null;
        longest_pause_seconds: number | null;
        response_completed_within_limit: boolean | null;
        screen_direction_percentage: number | null;
      };
      technical_observations: string[];
      neutral_summary: string;
    };
    per_response_observations?: Array<{
      question_index: number;
      question?: string;
      transcript?: string;
      video_observations: {
        face_visible_percentage: number | null;
        speaking_time_seconds: number | null;
        filler_word_count: number | null;
        long_pause_count: number | null;
        longest_pause_seconds?: number | null;
        response_completed_within_limit: boolean | null;
        screen_direction_percentage?: number | null;
        notes: string[];
      };
    }>;
  } | null;
  cv_consistency?: unknown;
  expires_at: string;
  created_at: string;
}> {
  return request(`/interviews/by-match/${encodeURIComponent(matchId)}`, {
    method: "GET",
  });
}

export function prepareProfileUplift(matchId: string): Promise<UpliftProfile> {
  return request(`/profile-uplifting/${encodeURIComponent(matchId)}/prepare`, {
    method: "POST",
  });
}

export async function getProfileUplifts(): Promise<UpliftProfile[]> {
  const response = await request<{ profiles: UpliftProfile[] }>("/profile-uplifting", {
    method: "GET",
  });
  return response.profiles ?? [];
}

export function getProfileUplift(matchId: string): Promise<UpliftProfile> {
  return request(`/profile-uplifting/${encodeURIComponent(matchId)}`, {
    method: "GET",
  });
}

export function saveProfileUplift(
  matchId: string,
  upliftedProfile: UpliftProfileContent,
): Promise<UpliftProfile> {
  return request(`/profile-uplifting/${encodeURIComponent(matchId)}`, {
    method: "PUT",
    body: JSON.stringify({
      uplifted_profile: upliftedProfile,
      confirm_factual_accuracy: true,
    }),
  });
}

export function generateProfileUplift(matchId: string): Promise<UpliftProfile> {
  return request(`/profile-uplifting/${encodeURIComponent(matchId)}/generate`, {
    method: "POST",
  });
}

export function resolveAPIUrl(path?: string | null) {
  if (!path) {
    return null;
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return buildUrl(path);
}
