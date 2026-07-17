"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Trophy } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { getJobs, getMatchesByJob, type Job, type Match } from "@/src/lib/api";
import { getJobId, getJobTitle, scoreToPercent } from "@/src/lib/utils";

type TopCandidate = { job: Job; match?: Match };

export default function TopCandidatesPage() {
  const [items, setItems] = useState<TopCandidate[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setIsLoading(true);
      const jobs = await getJobs();
      const nextItems = await Promise.all(
        jobs.map(async (job) => {
          const matches = await getMatchesByJob(getJobId(job));
          return { job, match: matches[0] };
        }),
      );
      setItems(nextItems);
      setIsLoading(false);
    }
    load().catch(() => setIsLoading(false));
  }, []);

  return (
    <>
      <PageHeader
        subtitle="Best-matching candidate for each active role"
        title="Top Candidate Summary"
      />
      {isLoading ? (
        <div className="flex min-h-[420px] items-center justify-center">
          <LoadingSpinner size="lg" />
        </div>
      ) : (
        <div className="space-y-5">
          {items.map(({ job, match }) => (
            <Card className="px-6 py-6" key={getJobId(job)}>
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-start gap-4">
                  <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#f6b800] text-[22px] font-bold text-white">
                    <Trophy className="h-7 w-7" />
                  </span>
                  <div>
                    <h2 className="text-[22px] font-bold text-[#333438]">{getJobTitle(job)}</h2>
                    <p className="mt-1 text-[15px] text-[#77777a]">
                      {match?.candidate_name ?? "No matched candidate yet"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  {match ? <Badge tone="green">{scoreToPercent(match.score)}% Match</Badge> : null}
                  <Link className="font-bold text-crimson-700" href={`/matches/${encodeURIComponent(getJobId(job))}`}>
                    View Matches
                  </Link>
                </div>
              </div>
            </Card>
          ))}
          {items.length === 0 ? (
            <Card className="px-6 py-10 text-center text-[14px] text-[#77777a]">
              No jobs available yet.
            </Card>
          ) : null}
        </div>
      )}
    </>
  );
}
