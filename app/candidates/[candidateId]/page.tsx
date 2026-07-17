import { CandidateDetail } from "@/components/candidates/CandidateDetail";

export default function CandidatePage({
  params,
}: {
  params: { candidateId: string };
}) {
  return <CandidateDetail candidateId={params.candidateId} />;
}
