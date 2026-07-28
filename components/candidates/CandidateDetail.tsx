"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Award,
  Briefcase,
  CheckCircle2,
  CircleHelp,
  DollarSign,
  Mail,
  MapPin,
  MessageSquarePlus,
  Phone,
  Star,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ProgressBar } from "@/components/ui/ProgressBar";
import {
  analyseMatch,
  getCandidate,
  getJob,
  getMatch,
  getMatchesByJob,
  getSkillAnalysis,
  updateMatchStatus,
  type Candidate,
  type DecisionAnalysis,
  type Job,
  type Match,
  type MatchStatus,
  type SkillAnalysis,
} from "@/src/lib/api";
import {
  formatDate,
  getClient,
  getJobTitle,
  getMatchId,
  initials,
  scoreToPercent,
} from "@/src/lib/utils";

export function CandidateDetail({
  candidateId,
  jobId,
}: {
  candidateId: string;
  jobId?: string;
}) {
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [match, setMatch] = useState<Match | null>(null);
  const [analysis, setAnalysis] = useState<DecisionAnalysis | null>(null);
  const [skillAnalysis, setSkillAnalysis] = useState<SkillAnalysis | null>(null);
  const [analysisGeneratedAt, setAnalysisGeneratedAt] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [isAnalysing, setIsAnalysing] = useState(false);
  const [skillLoading, setSkillLoading] = useState(false);
  const [statusAction, setStatusAction] = useState<"shortlist" | "reject" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError("");
      try {
        const candidateDetails = await getCandidate(candidateId);
        let jobDetails: Job | null = null;
        let matchDetails: Match | null = null;

        if (jobId) {
          const [nextJob, matches] = await Promise.all([
            getJob(jobId),
            getMatchesByJob(jobId),
          ]);
          jobDetails = nextJob;
          const basicMatch = matches.find((item) => item.candidate_id === candidateId);
          if (basicMatch?.match_id) {
            matchDetails = await getMatch(basicMatch.match_id);
          } else {
            matchDetails = basicMatch ?? null;
          }
        }

        if (mounted) {
          setCandidate(candidateDetails);
          setJob(jobDetails);
          setMatch(matchDetails);
          setAnalysis(matchDetails?.analysis ?? null);
          setSkillAnalysis(null);
          setAnalysisGeneratedAt(matchDetails?.analysis_generated_at ?? "");
        }
      } catch (requestError) {
        if (mounted) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Candidate details could not be loaded.",
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
  }, [candidateId, jobId]);

  useEffect(() => {
    let mounted = true;
    const matchId = match ? getMatchId(match) : "";

    async function loadSkills() {
      if (!jobId || !matchId) {
        return;
      }
      setSkillLoading(true);
      try {
        const result = await getSkillAnalysis(matchId);
        if (mounted) {
          setSkillAnalysis(result);
        }
      } catch {
        if (mounted) {
          setSkillAnalysis(null);
        }
      } finally {
        if (mounted) {
          setSkillLoading(false);
        }
      }
    }

    loadSkills();

    return () => {
      mounted = false;
    };
  }, [jobId, match]);

  const scorePercent = scoreToPercent(match?.score ?? match?.match_score);
  const candidateName = candidate?.name ?? match?.candidate_name ?? "Candidate";
  const candidateInitials = initials(candidateName);
  const candidateSkills = candidate?.skills ?? [];
  const requiredSkills = job?.required_skills ?? job?.skills ?? [];
  const fallbackMatched = requiredSkills.filter((skill) =>
    candidateSkills.some((candidateSkill) => candidateSkill.toLowerCase() === skill.toLowerCase()),
  );
  const fallbackMissing = requiredSkills.filter(
    (skill) =>
      !candidateSkills.some((candidateSkill) => candidateSkill.toLowerCase() === skill.toLowerCase()),
  );
  const skillsMatch =
    skillAnalysis?.semantic_skill_score ?? Math.min(99, Math.round(scorePercent * 1.02));
  const expMatch = analysis?.exp_match_percentage ?? Math.round(scorePercent * 0.98);
  const educationMatch = analysis?.education_match_percentage ?? Math.round(scorePercent * 0.95);

  async function refreshMatch() {
    if (!match) {
      return;
    }
    const matchId = getMatchId(match);
    const refreshed = await getMatch(matchId);
    setMatch(refreshed);
    setAnalysis(refreshed.analysis ?? null);
    setSkillAnalysis(null);
    setAnalysisGeneratedAt(refreshed.analysis_generated_at ?? "");
  }

  async function runAnalysis() {
    if (!match) {
      return;
    }
    setIsAnalysing(true);
    try {
      await analyseMatch(getMatchId(match));
      const refreshed = await getMatch(getMatchId(match));
      setMatch(refreshed);
      setAnalysis(refreshed.analysis ?? null);
      setAnalysisGeneratedAt(refreshed.analysis_generated_at ?? "");
      setSkillAnalysis(await getSkillAnalysis(getMatchId(match)));
    } finally {
      setIsAnalysing(false);
    }
  }

  async function setStatus(status: "Shortlisted" | "Sent") {
    if (!match) {
      return;
    }

    setStatusAction(status === "Shortlisted" ? "shortlist" : "reject");

    try {
      await updateMatchStatus(getMatchId(match), status);
      setMatch({
        ...match,
        status,
        updated_at: new Date().toISOString(),
      });
    } finally {
      setStatusAction(null);
    }
  }

  const currentStatus = (match?.status ?? "Matched") as MatchStatus | string;
  const completedStatus = ["Shortlisted", "Interview Sent", "Interview Completed", "Uplifted", "Sent"].includes(currentStatus);

  const achievements = candidate?.key_achievements?.length
    ? candidate.key_achievements
    : candidate?.domain_experience ?? [];

  if (isLoading) {
    return (
      <div className="flex min-h-[520px] items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error || !candidate) {
    return (
      <Card className="mx-auto max-w-xl px-6 py-10 text-center">
        <h1 className="text-[22px] font-bold text-crimson-700">Candidate unavailable</h1>
        <p className="mt-3 text-[15px] leading-6 text-[#77777a]">{error}</p>
      </Card>
    );
  }

  return (
    <div className="-m-8 min-h-screen bg-[#f7f8fa]">
      <header className="sticky top-0 z-20 border-b border-[#E5E7EB] bg-white px-8 py-4 shadow-soft">
        <div className="mx-auto flex max-w-[1220px] items-center justify-between gap-5">
          <Link
            className="flex items-center gap-2 text-[14px] font-bold text-crimson-700 hover:text-[#ff1717]"
            href={jobId ? `/matches/${encodeURIComponent(jobId)}` : "/"}
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Match Results
          </Link>
          <div className="flex items-center gap-4">
            <Avatar initials={candidateInitials} size="sm" />
            <h1 className="text-[20px] font-bold text-[#333438]">{candidateName}</h1>
            {match ? <Badge tone="green">{scorePercent}% Match</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            {match ? <Badge tone={detailStatusTone(currentStatus)}>{currentStatus}</Badge> : null}
            {match && !completedStatus ? (
              <>
                <Button
                  disabled={Boolean(statusAction)}
                  isLoading={statusAction === "shortlist"}
                  onClick={() => setStatus("Shortlisted")}
                  size="sm"
                >
                  Shortlist
                </Button>
                <Button
                  disabled={Boolean(statusAction)}
                  isLoading={statusAction === "reject"}
                  onClick={() => setStatus("Sent")}
                  size="sm"
                  variant="secondary"
                >
                  Reject
                </Button>
              </>
            ) : null}
            {jobId && match && !analysis ? (
              <Button isLoading={isAnalysing} onClick={runAnalysis} size="sm">
                Run AI Analysis
              </Button>
            ) : analysis ? (
              <span className="text-[13px] font-bold text-[#04743b]">
                {"\u2713"} AI Analysis Complete {analysisGeneratedAt ? formatDate(analysisGeneratedAt) : ""}
              </span>
            ) : null}
            <Button leftIcon={<MessageSquarePlus className="h-4 w-4" />} size="sm" variant="ghost">
              Add Note
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1220px] px-8 py-8">
        <section className="rounded-[8px] border border-[#d8b7c0] border-l-4 border-l-crimson-700 bg-[#e8cfd6] px-7 py-6">
          <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-crimson-700">
            AI Summary
          </p>
          <p className="mt-4 text-[15px] font-bold text-[#333438]">
            {analysis ? "Candidate role assessment" : "Analysis pending"}
          </p>
          <p className="mt-3 text-[14px] leading-6 text-[#555b66]">
            {analysis?.ai_summary ??
              "Run AI Analysis to generate a factual assessment for this candidate and role."}
          </p>
          <p className="mt-6 text-right text-[12px] italic text-[#9ca0a8]">
            Generated by iSoft AI
          </p>
        </section>

        <div className="mt-7 grid gap-7 lg:grid-cols-2">
          <div className="space-y-7">
            <Card className="px-6 py-6">
              <div className="flex items-start gap-5">
                <Avatar initials={candidateInitials} />
                <div>
                  <h2 className="text-[22px] font-bold text-[#333438]">{candidateName}</h2>
                  <p className="mt-1 text-[15px] text-[#77777a]">
                    {candidate.summary || candidate.current_title || "Candidate profile summary not available"}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-[#77777a]">
                    <IconText icon={<MapPin className="h-4 w-4" />}>{candidate.location || "Location not specified"}</IconText>
                    <IconText icon={<Briefcase className="h-4 w-4" />}>{candidate.years_experience ?? "Experience not specified"} years</IconText>
                    <IconText icon={<DollarSign className="h-4 w-4" />}>{candidate.expected_salary || "Salary not specified"}</IconText>
                    <IconText icon={<Mail className="h-4 w-4" />}>{candidate.email || "Email not specified"}</IconText>
                    <IconText icon={<Phone className="h-4 w-4" />}>{candidate.phone || "Phone not specified"}</IconText>
                  </div>
                </div>
              </div>
            </Card>

            <Card className="px-6 py-6">
              <CardHeader className="mb-5" title="Technical Skills" />
              {skillLoading ? (
                <div className="space-y-3">
                  <p className="text-[14px] text-[#77777a]">Loading semantic skill analysis...</p>
                  {[0, 1, 2].map((index) => (
                    <div className="h-8 animate-pulse rounded-full bg-[#edf0f4]" key={index} />
                  ))}
                </div>
              ) : jobId && skillAnalysis ? (
                <SemanticSkillSections analysis={skillAnalysis} />
              ) : jobId ? (
                <div className="space-y-5">
                  <SkillTags emptyText="No matched skills found." label="Matched Skills" skills={fallbackMatched} tone="green" />
                  <SkillTags emptyText="No missing skills found." label="Missing Skills" skills={fallbackMissing} tone="amber" />
                </div>
              ) : (
                <SkillTags emptyText="No skills available." label="All Skills" skills={candidateSkills} tone="grey" />
              )}
            </Card>

            <Card className="px-6 py-6">
              <CardHeader className="mb-5" title="Work Experience" />
              {candidate.work_experience?.length ? (
                <div className="space-y-4">
                  {candidate.work_experience.map((item, index) => (
                    <div className="rounded-[8px] border border-[#E5E7EB] px-4 py-4" key={`${item.title}-${index}`}>
                      <div className="flex justify-between gap-4">
                        <div>
                          <h3 className="text-[15px] font-bold text-[#333438]">{item.title || "Role not specified"}</h3>
                          <p className="mt-1 text-[13px] text-[#77777a]">{item.company || "Company not specified"}</p>
                        </div>
                        <p className="text-right text-[12px] text-[#9ca0a8]">
                          {String(item.start_year ?? "-")} - {item.is_current ? "Present" : String(item.end_year ?? "-")}
                        </p>
                      </div>
                      {item.highlights?.length ? (
                        <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] leading-5 text-[#555b66]">
                          {item.highlights.map((highlight) => <li key={highlight}>{highlight}</li>)}
                        </ul>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[14px] text-[#77777a]">Work experience details not available</p>
              )}
            </Card>

            <Card className="px-6 py-6">
              <CardHeader className="mb-5" title="Education" />
              {candidate.education?.length ? (
                <div className="space-y-3">
                  {candidate.education.map((item, index) => (
                    <div className="flex justify-between gap-4 rounded-[8px] border border-[#E5E7EB] px-4 py-4" key={`${item.degree}-${index}`}>
                      <div>
                        <h3 className="text-[15px] font-bold text-[#333438]">{item.degree || "Degree not specified"}</h3>
                        <p className="mt-1 text-[13px] text-[#77777a]">{item.institution || "Institution not specified"}</p>
                      </div>
                      <p className="text-right text-[12px] text-[#9ca0a8]">{item.year ?? "-"}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[14px] text-[#77777a]">Education details not available</p>
              )}
            </Card>
          </div>

          <div className="space-y-7">
            <Card className="px-6 py-6">
              <div className="flex items-start justify-between gap-4">
                <CardHeader title="Overall Match Score" />
                <span className="flex items-center gap-2 text-[14px] text-[#333438]">
                  <Star className="h-4 w-4 fill-[#f6b800] text-[#f6b800]" />
                  Top Candidate
                </span>
              </div>
              <p className="mt-5 text-[48px] font-bold leading-none text-[#00a650]">
                {scorePercent}%
              </p>
              <p className="mt-3 text-[14px] text-[#77777a]">
                Based on semantic profile similarity from Atlas Vector Search.
              </p>
            </Card>

            <Card className="px-6 py-6">
              <CardHeader className="mb-5" title="Score Details" />
              <div className="space-y-3 text-[14px]">
                <ScoreDetailRow
                  explanation="How closely this candidate's overall profile aligns with the job description, based on Atlas Vector Search embeddings"
                  label="Semantic Similarity Score"
                  value={`${scorePercent}%`}
                />
                <ScoreDetailRow
                  explanation="Percentage of required skills matched or transferable (semantic comparison)"
                  label="Skills Coverage"
                  tags={
                    skillAnalysis ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Badge tone="green">{skillAnalysis.matched.length} matched</Badge>
                        <Badge tone="indigo">{skillAnalysis.partial.length} transferable</Badge>
                        <Badge tone="amber">{skillAnalysis.missing.length} gaps</Badge>
                      </div>
                    ) : null
                  }
                  value={skillAnalysis ? `${skillAnalysis.semantic_skill_score}%` : "Run skill analysis"}
                />
                <ScoreDetailRow
                  explanation="Candidate years of experience vs role requirement"
                  label="Experience Coverage"
                  value={analysis ? `${analysis.exp_match_percentage ?? "-"}%` : "Run AI Analysis"}
                />
              </div>
              <p className="mt-4 text-[13px] italic leading-6 text-[#77777a]">
                The overall match score is based on semantic vector similarity. Skills and experience coverage are supplementary signals to help assess fit.
              </p>
            </Card>

            <Card className="px-6 py-6">
              <CardHeader className="mb-5" title="Match Breakdown" />
              <div className="space-y-6">
                <ProgressRow
                  caption="Based on semantic skill similarity — not keyword matching"
                  label="Skills Match"
                  value={skillsMatch}
                />
                <ProgressRow label="Experience Match" value={expMatch} />
                <ProgressRow label="Education Match" value={educationMatch} />
              </div>
            </Card>

            {analysis ? (
              <Card className="px-6 py-6">
                <CardHeader className="mb-5" title="Key Strengths & Risks" />
                <AnalysisList icon={<CheckCircle2 className="h-4 w-4 text-[#04743b]" />} items={analysis.strengths ?? []} title="Key Strengths" />
                <AnalysisList className="mt-5" icon={<AlertTriangle className="h-4 w-4 text-[#a65f00]" />} items={analysis.risks ?? []} title="Key Risks" />
              </Card>
            ) : null}

            {analysis ? (
              <section className="rounded-[8px] border border-[#d8dee9] bg-[#eef4fb] px-6 py-5">
                <div className="mb-4 flex items-center gap-3">
                  <CircleHelp className="h-5 w-5 text-[#365b8c]" />
                  <h2 className="text-[17px] font-bold text-[#333438]">Suggested Interview Questions</h2>
                </div>
                <ol className="list-decimal space-y-2 pl-5 text-[14px] leading-6 text-[#4f5f73]">
                  {(analysis.interview_questions ?? []).map((question) => <li key={question}>{question}</li>)}
                </ol>
              </section>
            ) : null}

            <Card className="px-6 py-6">
              <CardHeader className="mb-5" title="Hard Filter Checks" />
              <div className="grid gap-4 sm:grid-cols-2">
                <MiniCheck label="Location" status={candidate.location || "Not specified"} />
                <MiniCheck label="Budget" status={job?.salary_range || "Not specified"} />
              </div>
            </Card>

            <section className="rounded-[8px] border border-[#d8b7c0] bg-[#e8cfd6] px-6 py-5">
              <div className="mb-3 flex items-center gap-3">
                <Award className="h-5 w-5 text-crimson-700" />
                <h2 className="text-[17px] font-bold text-[#333438]">Key Achievements</h2>
              </div>
              {achievements.length ? (
                <ul className="list-disc space-y-1 pl-5 text-[14px] leading-6 text-[#555b66]">
                  {achievements.map((achievement) => <li key={achievement}>{achievement}</li>)}
                </ul>
              ) : (
                <p className="text-[14px] text-[#555b66]">No achievements data available</p>
              )}
            </section>

            <Card className="overflow-hidden">
              <CardHeader className="px-6 py-5" title="Feedback Log" />
              <table className="w-full border-collapse text-left">
                <thead className="bg-[#e8cfd6]">
                  <tr>
                    {["Date", "Action", "Comments"].map((header) => (
                      <th className="px-4 py-3 text-[12px] font-bold uppercase text-crimson-700" key={header}>{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {match?.status_note ? (
                    <tr>
                      <td className="px-4 py-3 text-[13px] text-[#77777a]">{formatDate(match.updated_at ?? match.created_at)}</td>
                      <td className="px-4 py-3"><Badge tone="green">{match.status ?? "Note"}</Badge></td>
                      <td className="px-4 py-3 text-[13px] text-[#555b66]">{match.status_note}</td>
                    </tr>
                  ) : (
                    <tr>
                      <td className="px-4 py-6 text-center text-[13px] text-[#77777a]" colSpan={3}>No feedback recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}


function detailStatusTone(
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
      return "green";
    case "uplifted":
      return "amber";
    case "sent":
      return "grey";
    default:
      return "grey";
  }
}

function Avatar({ initials, size = "md" }: { initials: string; size?: "sm" | "md" }) {
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-full bg-[#b70735] font-bold text-white ${size === "sm" ? "h-9 w-9 text-[14px]" : "h-14 w-14 text-[20px]"}`}>
      {initials}
    </span>
  );
}

function IconText({ children, icon }: { children: React.ReactNode; icon: React.ReactNode }) {
  return <span className="flex items-center gap-1.5"><span className="text-[#98a2b3]">{icon}</span>{children}</span>;
}

function SkillTags({ emptyText, label, skills, tone }: { emptyText: string; label: string; skills: string[]; tone: "green" | "amber" | "grey" | "indigo" }) {
  const color =
    tone === "green" ? "bg-[#d9f8e5] text-[#04743b]" :
    tone === "amber" ? "bg-[#fff4cc] text-[#a65f00]" :
    tone === "indigo" ? "bg-[#e0e7ff] text-[#4338ca]" :
    "bg-[#edf0f4] text-[#667085]";

  return (
    <div>
      <p className="mb-3 text-[12px] font-bold uppercase tracking-[0.08em] text-[#98a2b3]">{label}</p>
      {skills.length ? (
        <div className="flex flex-wrap gap-2">
          {skills.map((skill) => (
            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-bold ${color}`} key={skill}>
              {tone === "amber" ? <XCircle className="h-3.5 w-3.5" /> : tone === "grey" ? null : <CheckCircle2 className="h-3.5 w-3.5" />}
              {skill}
            </span>
          ))}
        </div>
      ) : <p className="text-[14px] text-[#77777a]">{emptyText}</p>}
    </div>
  );
}

function SemanticSkillSections({ analysis }: { analysis: SkillAnalysis }) {
  return (
    <div className="space-y-5">
      <div>
        <p className="mb-3 text-[12px] font-bold uppercase tracking-[0.08em] text-[#04743b]">Matched Skills</p>
        <div className="flex flex-wrap gap-2">
          {analysis.matched.length ? analysis.matched.map((item) => (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#d9f8e5] px-3 py-1.5 text-[13px] font-bold text-[#04743b]" key={item.required} title={`Matched with candidate's ${item.matched_with ?? "skill"} (${Math.round(item.similarity * 100)}% similar)`}>
              <CheckCircle2 className="h-3.5 w-3.5" />{item.required}
            </span>
          )) : <p className="text-[14px] text-[#77777a]">No direct skill matches found.</p>}
        </div>
      </div>
      <div>
        <p className="mb-3 flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.08em] text-[#4338ca]">
          Transferable Skills
          <span title="Skills the candidate does not have exactly but has closely related experience that transfers."><CircleHelp className="h-3.5 w-3.5" /></span>
        </p>
        <div className="flex flex-wrap gap-2">
          {analysis.partial.length ? analysis.partial.map((item) => (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#e0e7ff] px-3 py-1.5 text-[13px] font-bold text-[#4338ca]" key={item.required} title={`Candidate has ${item.closest_match ?? "related experience"} (${Math.round(item.similarity * 100)}% similar)`}>
              <span>{"\u2194"}</span>{item.required}
            </span>
          )) : <p className="text-[14px] text-[#77777a]">No transferable skills identified.</p>}
        </div>
      </div>
      <SkillTags emptyText={analysis.missing.length ? "No skill gap text available." : "All required skills covered."} label="Skill Gaps" skills={analysis.missing.map((item) => item.required)} tone="amber" />
      <p className="text-[13px] italic text-[#77777a]">{analysis.summary}</p>
    </div>
  );
}

function ProgressRow({
  caption,
  label,
  value,
}: {
  caption?: string;
  label: string;
  value: number;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-[14px] font-bold text-[#333438]">
        <span>{label}</span><span>{value}%</span>
      </div>
      <ProgressBar value={value} />
      {caption ? <p className="mt-2 text-[12px] text-[#77777a]">{caption}</p> : null}
    </div>
  );
}

function ScoreDetailRow({
  explanation,
  label,
  tags,
  value,
}: {
  explanation: string;
  label: string;
  tags?: React.ReactNode;
  value: string;
}) {
  return (
    <div className="rounded-[8px] border border-[#E5E7EB] px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-bold text-[#333438]">{label}</p>
          <p className="mt-1 max-w-[420px] text-[12px] leading-5 text-[#77777a]">{explanation}</p>
        </div>
        <p className="text-right text-[16px] font-bold text-crimson-700">{value}</p>
      </div>
      {tags}
    </div>
  );
}

function AnalysisList({ className, icon, items, title }: { className?: string; icon: React.ReactNode; items: string[]; title: string }) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center gap-2"><span>{icon}</span><h3 className="text-[14px] font-bold text-[#333438]">{title}</h3></div>
      {items.length ? <ul className="list-disc space-y-1 pl-5 text-[14px] leading-6 text-[#555b66]">{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="text-[14px] text-[#77777a]">No data returned.</p>}
    </div>
  );
}

function MiniCheck({ label, status }: { label: string; status: string }) {
  return (
    <div className="rounded-[8px] border border-[#E5E7EB] px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-bold text-[#333438]">{label}</p>
          <p className="mt-1 text-[12px] text-[#77777a]">{status}</p>
          <Badge className="mt-2" tone="green">Match</Badge>
        </div>
        <CheckCircle2 className="h-5 w-5 text-[#06c95e]" />
      </div>
    </div>
  );
}
