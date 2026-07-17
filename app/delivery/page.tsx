import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/Card";

export default function DeliveryPage() {
  return (
    <>
      <PageHeader
        subtitle="Send uplifted candidate profiles to your client"
        title="Client Delivery"
      />
      <Card className="px-6 py-16 text-center">
        <h2 className="text-[22px] font-bold text-[#333438]">Coming soon</h2>
        <p className="mt-3 text-[15px] text-[#77777a]">
          Client delivery tools will appear here.
        </p>
      </Card>
    </>
  );
}
