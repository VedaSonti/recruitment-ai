import { CandidateDetail } from "@/components/candidates/CandidateDetail";

export default function MatchCandidatePage({
  params,
}: {
  params: { jobId: string; candidateId: string };
}) {
  return (
    <CandidateDetail
      candidateId={params.candidateId}
      jobId={params.jobId}
    />
  );
}
