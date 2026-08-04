"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, FileText, RefreshCw, Save } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import {
  generateProfileUplift,
  getProfileUplift,
  getProfileUplifts,
  resolveAPIUrl,
  saveProfileUplift,
  type UpliftProfile,
  type UpliftProfileContent,
} from "@/src/lib/api";
import { formatDate } from "@/src/lib/utils";

const SECTION_LABELS: Record<string, string> = {
  contact: "Contact details",
  summary: "Professional summary",
  skills: "Skills",
  experience: "Experience",
  achievements: "Achievements",
  education: "Education",
  certifications: "Certifications",
  additional: "Additional information",
};

export default function UpliftPage() {
  const [profiles, setProfiles] = useState<UpliftProfile[]>([]);
  const [selected, setSelected] = useState<UpliftProfile | null>(null);
  const [draft, setDraft] = useState<UpliftProfileContent | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<"save" | "generate" | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function load() {
      setLoading(true);
      const allProfiles = await getProfileUplifts();
      if (!mounted) return;
      setProfiles(allProfiles);
      const requestedMatchId = new URLSearchParams(window.location.search).get("matchId");
      const initial = requestedMatchId
        ? await getProfileUplift(requestedMatchId)
        : allProfiles[0] ?? null;
      if (!mounted) return;
      setSelected(initial);
      setDraft(initial?.uplifted_profile ?? null);
      setConfirmed(Boolean(initial?.verified_by_recruiter_at));
      setLoading(false);
    }
    load().catch((loadError) => {
      if (mounted) {
        setError(loadError instanceof Error ? loadError.message : "Could not load profiles.");
        setLoading(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  function chooseProfile(profile: UpliftProfile) {
    setSelected(profile);
    setDraft(profile.uplifted_profile);
    setConfirmed(Boolean(profile.verified_by_recruiter_at));
    setMessage("");
    setError("");
    window.history.replaceState(null, "", `/uplift?matchId=${encodeURIComponent(profile.match_id)}`);
  }

  function updateDraft(update: Partial<UpliftProfileContent>) {
    setDraft((current) => (current ? { ...current, ...update } : current));
    setConfirmed(false);
    setMessage("");
  }

  async function saveDraft() {
    if (!selected || !draft || !confirmed) {
      setError("Confirm that all edits remain grounded in the original CV before saving.");
      return null;
    }
    setAction("save");
    setError("");
    try {
      const updated = await saveProfileUplift(selected.match_id, draft);
      setSelected(updated);
      setDraft(updated.uplifted_profile);
      setProfiles((current) => current.map((profile) => profile.match_id === updated.match_id ? updated : profile));
      setMessage("Draft saved. The original candidate record was not changed.");
      return updated;
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save the profile.");
      return null;
    } finally {
      setAction(null);
    }
  }

  async function generateFinal() {
    if (!selected || !draft || !confirmed) {
      setError("Confirm factual accuracy before generating the final CV.");
      return;
    }
    setAction("generate");
    setError("");
    try {
      await saveProfileUplift(selected.match_id, draft);
      const generated = await generateProfileUplift(selected.match_id);
      setSelected(generated);
      setDraft(generated.uplifted_profile);
      setProfiles((current) => current.map((profile) => profile.match_id === generated.match_id ? generated : profile));
      setMessage("Final branded CV generated and ready for recruiter download.");
    } catch (generateError) {
      setError(generateError instanceof Error ? generateError.message : "Could not generate the final CV.");
    } finally {
      setAction(null);
    }
  }

  const selectedDownloadUrl = resolveAPIUrl(selected?.download_url);
  const originalDownloadUrl = resolveAPIUrl(selected?.original_cv_reference.download_url);

  return (
    <>
      <PageHeader
        subtitle="Review, edit, and generate client-ready profiles from verified CV information"
        title="Profile Uplifting"
      />

      {loading ? (
        <Card className="flex min-h-[280px] items-center justify-center"><LoadingSpinner /></Card>
      ) : error && profiles.length === 0 ? (
        <Card className="border-red-200 bg-red-50 px-6 py-10 text-center text-red-700">{error}</Card>
      ) : profiles.length === 0 ? (
        <Card className="px-6 py-16 text-center">
          <FileText className="mx-auto text-crimson-700" size={38} />
          <h2 className="mt-4 text-[22px] font-bold text-[#333438]">No profiles ready yet</h2>
          <p className="mt-3 text-[15px] text-[#77777a]">
            Candidates appear here after a recruiter selects Proceed to Next Stage.
          </p>
        </Card>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[290px_minmax(0,1fr)]">
          <Card className="overflow-hidden p-0">
            <div className="border-b border-[#E5E7EB] px-5 py-4">
              <h2 className="font-bold text-[#333438]">Profiles Ready for Uplifting</h2>
              <p className="mt-1 text-[12px] text-[#77777a]">{profiles.length} candidate{profiles.length === 1 ? "" : "s"}</p>
            </div>
            <div className="max-h-[720px] overflow-y-auto">
              {profiles.map((profile) => (
                <button
                  className={`w-full border-b border-[#E5E7EB] px-5 py-4 text-left transition ${selected?.match_id === profile.match_id ? "bg-[#F2E1E3]" : "hover:bg-[#fafafa]"}`}
                  key={profile.match_id}
                  onClick={() => chooseProfile(profile)}
                  type="button"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-bold text-[#333438]">{profile.candidate_name}</p>
                      <p className="mt-1 text-[13px] text-[#667085]">{profile.target_job}</p>
                    </div>
                    <Badge tone={profile.uplift_status === "Generated" ? "green" : profile.uplift_status === "Draft" ? "amber" : "blue"}>{profile.uplift_status}</Badge>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center text-[11px] text-[#667085]">
                    <Score label="Profile" value={profile.profile_match_score} />
                    <Score label="Interview" value={profile.interview_score} />
                    <Score label="Combined" value={profile.combined_score} />
                  </div>
                  <p className="mt-3 text-[11px] text-[#98A2B3]">Updated {formatDate(profile.updated_at)}</p>
                </button>
              ))}
            </div>
          </Card>

          {selected && draft ? (
            <div className="space-y-6">
              <Card className="px-6 py-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="flex flex-wrap items-center gap-3">
                      <h2 className="text-[24px] font-bold text-[#333438]">{selected.candidate_name}</h2>
                      <Badge tone="amber">{selected.workflow_status}</Badge>
                    </div>
                    <p className="mt-1 text-[14px] text-[#667085]">Target role: {selected.target_job}</p>
                    <p className="mt-2 text-[13px] text-[#77777a]">
                      Original CV: {selected.original_cv_reference.source_file || "Reference unavailable"}
                      {originalDownloadUrl ? <a className="ml-2 font-bold text-crimson-700" href={originalDownloadUrl}>Download original</a> : <span className="ml-2 text-amber-700">Historical file unavailable; parsed CV data is preserved.</span>}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button isLoading={action === "save"} leftIcon={<Save size={16} />} onClick={saveDraft} variant="secondary">Save Draft</Button>
                    <Button isLoading={action === "generate"} leftIcon={<RefreshCw size={16} />} onClick={generateFinal}>Generate Final CV</Button>
                    {selectedDownloadUrl ? <a href={selectedDownloadUrl}><Button leftIcon={<Download size={16} />} variant="secondary">Download</Button></a> : null}
                  </div>
                </div>
                {message ? <p className="mt-4 rounded-[8px] border border-green-200 bg-green-50 p-3 text-[13px] text-green-700">{message}</p> : null}
                {error ? <p className="mt-4 rounded-[8px] border border-red-200 bg-red-50 p-3 text-[13px] text-red-700">{error}</p> : null}
              </Card>

              <div className="grid items-start gap-6 2xl:grid-cols-[420px_minmax(0,1fr)]">
                <ProfileEditor draft={draft} confirmed={confirmed} onConfirm={setConfirmed} onUpdate={updateDraft} />
                <BrandedPreview profile={draft} />
              </div>
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}

function ProfileEditor({ draft, confirmed, onConfirm, onUpdate }: { draft: UpliftProfileContent; confirmed: boolean; onConfirm: (value: boolean) => void; onUpdate: (update: Partial<UpliftProfileContent>) => void }) {
  const updateList = (key: "core_skills" | "technical_skills" | "key_achievements" | "certifications", value: string) => {
    onUpdate({ [key]: value.split("\n").map((item) => item.trim()).filter(Boolean) });
  };
  return (
    <Card className="space-y-5 px-5 py-5">
      <div><h3 className="text-[18px] font-bold text-[#333438]">Editable Profile Fields</h3><p className="mt-1 text-[12px] leading-5 text-[#77777a]">Reword only information already supported by the original CV. Interview answers are not included.</p></div>
      <Field label="Professional title"><input className="field" value={draft.professional_title} onChange={(event) => onUpdate({ professional_title: event.target.value })} /></Field>
      <Field label="Professional summary"><textarea className="field min-h-[130px]" value={draft.professional_summary} onChange={(event) => onUpdate({ professional_summary: event.target.value })} /></Field>
      <Field label="Core skills - one per line"><textarea className="field min-h-[120px]" value={draft.core_skills.join("\n")} onChange={(event) => updateList("core_skills", event.target.value)} /></Field>
      <Field label="Technical skills - one per line"><textarea className="field min-h-[100px]" value={draft.technical_skills.join("\n")} onChange={(event) => updateList("technical_skills", event.target.value)} /></Field>
      <div>
        <p className="mb-3 text-[13px] font-bold text-[#333438]">Experience bullets</p>
        <div className="space-y-4">
          {draft.professional_experience.map((role, roleIndex) => (
            <div className="rounded-[8px] border border-[#E5E7EB] p-3" key={`${role.company}-${role.title}-${roleIndex}`}>
              <p className="text-[13px] font-bold text-[#5C0D1B]">{role.title || "Role"} {role.company ? `| ${role.company}` : ""}</p>
              <textarea
                className="field mt-2 min-h-[110px]"
                value={(role.highlights ?? []).join("\n")}
                onChange={(event) => {
                  const roles = draft.professional_experience.map((item, index) => index === roleIndex ? { ...item, highlights: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean) } : item);
                  onUpdate({ professional_experience: roles });
                }}
              />
            </div>
          ))}
        </div>
      </div>
      <Field label="Achievements - one per line"><textarea className="field min-h-[100px]" value={draft.key_achievements.join("\n")} onChange={(event) => updateList("key_achievements", event.target.value)} /></Field>
      <div><p className="mb-3 text-[13px] font-bold text-[#333438]">Section visibility</p><div className="grid gap-2 sm:grid-cols-2">{Object.entries(SECTION_LABELS).map(([key, label]) => <label className="flex items-center gap-2 text-[13px] text-[#555b66]" key={key}><input checked={draft.section_visibility[key] !== false} onChange={(event) => onUpdate({ section_visibility: { ...draft.section_visibility, [key]: event.target.checked } })} type="checkbox" />{label}</label>)}</div></div>
      <label className="flex items-start gap-3 rounded-[8px] border border-[#D9B9BE] bg-[#F2E1E3] p-4 text-[13px] leading-5 text-[#5C0D1B]"><input checked={confirmed} className="mt-1" onChange={(event) => onConfirm(event.target.checked)} type="checkbox" /><span>I confirm these edits are factually grounded in the candidate&apos;s original CV or recruiter-approved corrections.</span></label>
    </Card>
  );
}

function BrandedPreview({ profile }: { profile: UpliftProfileContent }) {
  const visible = profile.section_visibility;
  return (
    <div className="overflow-auto rounded-[8px] bg-[#eceef1] p-5 shadow-inner">
      <article className="mx-auto min-h-[980px] w-full max-w-[760px] border-[5px] border-[#5C0D1B] bg-white p-3 shadow-xl">
        <header className="bg-[#5C0D1B] px-7 py-6 text-white"><div className="flex items-start justify-between gap-5"><div><h2 className="font-serif text-[31px] font-bold uppercase tracking-wide">{profile.name}</h2><p className="mt-2 font-serif text-[15px] font-bold uppercase">{profile.professional_title || "Professional Profile"}</p></div><p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[#E01111]">Candidate Profile</p></div></header>
        {visible.contact !== false && Object.values(profile.contact).some(Boolean) ? <div className="grid grid-cols-3 gap-3 border-b border-[#D9B9BE] bg-[#F2E1E3] px-5 py-2 text-center font-serif text-[12px] text-[#5C0D1B]"><span>{profile.contact.location}</span><span>{profile.contact.phone}</span><span>{profile.contact.email}</span></div> : null}
        <div className="grid min-h-[760px] md:grid-cols-[36%_64%]">
          <aside className="bg-[#5C0D1B] px-5 py-7 font-serif text-white">
            {visible.skills !== false && [...profile.core_skills, ...profile.technical_skills].length ? <PreviewSection dark title="Core & Technical Skills"><ul className="space-y-1">{[...profile.core_skills, ...profile.technical_skills].map((skill) => <li key={skill}>• {skill}</li>)}</ul></PreviewSection> : null}
            {visible.education !== false && profile.education.length ? <PreviewSection dark title="Education">{profile.education.map((item, index) => <div className="mb-3" key={`${item.degree}-${index}`}><p className="font-bold">{item.degree}</p><p>{item.institution}</p><p>{item.year}</p></div>)}</PreviewSection> : null}
            {visible.certifications !== false && profile.certifications.length ? <PreviewSection dark title="Certifications"><ul>{profile.certifications.map((item) => <li key={item}>• {item}</li>)}</ul></PreviewSection> : null}
            {visible.additional !== false ? <PreviewSection dark title="Additional Information"><p>{profile.additional_information.work_rights}</p><p>{profile.additional_information.notice_period}</p></PreviewSection> : null}
          </aside>
          <main className="border-l-2 border-[#E01111] px-6 py-7 font-serif text-[#333333]">
            <p className="text-[12px] font-bold uppercase text-[#E01111]">Candidate Profile</p>
            {visible.summary !== false && profile.professional_summary ? <PreviewSection title="Professional Summary"><p>{profile.professional_summary}</p></PreviewSection> : null}
            {visible.experience !== false && profile.professional_experience.length ? <PreviewSection title="Professional Experience">{profile.professional_experience.map((role, index) => <div className="mb-5" key={`${role.company}-${index}`}><p className="font-bold uppercase">{role.title} <span className="text-[#E01111]">{role.company ? `| ${role.company}` : ""}</span></p><p className="text-[12px] text-[#667085]">{role.start_year} - {role.is_current ? "Present" : role.end_year}</p><ul className="mt-2 space-y-1">{role.highlights?.map((highlight) => <li key={highlight}>• {highlight}</li>)}</ul></div>)}</PreviewSection> : null}
            {visible.achievements !== false && profile.key_achievements.length ? <PreviewSection title="Key Projects & Achievements"><ul>{profile.key_achievements.map((item) => <li key={item}>• {item}</li>)}</ul></PreviewSection> : null}
          </main>
        </div>
        <footer className="py-3 text-center font-serif text-[10px] text-[#667085]">Candidate Profile | Confidential | Recruiter Review Required</footer>
      </article>
    </div>
  );
}

function Field({ children, label }: { children: React.ReactNode; label: string }) { return <label className="block"><span className="mb-2 block text-[13px] font-bold text-[#333438]">{label}</span>{children}</label>; }
function Score({ label, value }: { label: string; value?: number | null }) { return <div className="rounded bg-white/70 px-1 py-2"><p>{label}</p><p className="mt-1 font-bold text-[#333438]">{typeof value === "number" ? value : "-"}</p></div>; }
function PreviewSection({ children, dark = false, title }: { children: React.ReactNode; dark?: boolean; title: string }) { return <section className="mt-5"><h3 className={`mb-2 font-serif text-[19px] font-bold ${dark ? "text-white" : "text-[#5C0D1B]"}`}>{title}</h3><div className="text-[13px] leading-5">{children}</div></section>; }
