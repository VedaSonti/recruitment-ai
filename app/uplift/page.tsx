import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/Card";

export default function UpliftPage() {
  return (
    <>
      <PageHeader
        subtitle="Generate premium iSoft profiles for shortlisted candidates"
        title="Profile Uplifting"
      />
      <Card className="px-6 py-16 text-center">
        <h2 className="text-[22px] font-bold text-[#333438]">Coming soon</h2>
        <p className="mt-3 text-[15px] text-[#77777a]">
          Profile uplifting workflows will appear here.
        </p>
      </Card>
    </>
  );
}
