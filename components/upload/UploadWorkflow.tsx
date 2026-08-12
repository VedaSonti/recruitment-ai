"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, FileText, UploadCloud, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/ProgressBar";
import {
  isAPIError,
  type UploadResponse,
} from "@/src/lib/api";
import { cx, fileSize } from "@/src/lib/utils";

type QueueStatus = "waiting" | "uploading" | "processed" | "duplicate" | "failed";

type QueueItem = {
  id: string;
  file: File;
  progress: number;
  status: QueueStatus;
  error?: string;
};

export type ManualJobDetails = {
  clientName?: string;
  location?: string;
  salaryRange?: string;
  experienceRequired?: string;
};

export function UploadWorkflow({
  accept = ".pdf,.docx",
  browseLabel = "Browse Files",
  dropTitle,
  helperText,
  manualDetails,
  onClear,
  onProcessed,
  upload,
}: {
  accept?: string;
  browseLabel?: string;
  dropTitle: string;
  helperText: string;
  manualDetails?: boolean;
  onClear?: () => void;
  onProcessed?: (count: number) => void;
  upload: (file: File, details?: ManualJobDetails) => Promise<UploadResponse>;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const timerRef = useRef<number | null>(null);
  const onProcessedRef = useRef(onProcessed);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const [details, setDetails] = useState<ManualJobDetails>({});

  const processedCount = queue.filter((item) => item.status === "processed").length;

  useEffect(() => {
    onProcessedRef.current = onProcessed;
  }, [onProcessed]);

  useEffect(() => {
    if (processedCount > 0) {
      onProcessedRef.current?.(processedCount);
    }
  }, [processedCount]);

  useEffect(
    () => () => {
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
      }
    },
    [],
  );

  function addFiles(files: FileList | File[]) {
    const nextFiles = Array.from(files).filter((file) =>
      /\.(pdf|docx)$/i.test(file.name),
    );

    setQueue((current) => [
      ...current,
      ...nextFiles.map((file) => ({
        id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
        file,
        progress: 0,
        status: "waiting" as const,
      })),
    ]);
  }

  function updateItem(id: string, update: Partial<QueueItem>) {
    setQueue((current) =>
      current.map((item) => (item.id === id ? { ...item, ...update } : item)),
    );
  }

  function removeItem(id: string) {
    setQueue((current) =>
      current.filter((item) => item.id !== id || item.status === "uploading"),
    );
  }

  async function uploadOne(item: QueueItem) {
    updateItem(item.id, { error: undefined, progress: 0, status: "uploading" });

    if (timerRef.current) {
      window.clearInterval(timerRef.current);
    }

    const startedAt = Date.now();
    timerRef.current = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const progress = Math.min(90, Math.round((elapsed / 15000) * 90));
      updateItem(item.id, { progress });
    }, 250);

    try {
      await upload(item.file, details);
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
      updateItem(item.id, { progress: 100, status: "processed" });
    } catch (error) {
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }

      if (
        (isAPIError(error) && error.status === 409) ||
        (error instanceof Error &&
          error.message.toLowerCase().includes("already been uploaded"))
      ) {
        updateItem(item.id, {
          error: "This file has already been uploaded",
          progress: 0,
          status: "duplicate",
        });
      } else {
        updateItem(item.id, {
          error:
            error instanceof Error
              ? error.message
              : "Upload failed. Please try again.",
          progress: 100,
          status: "failed",
        });
      }
    }
  }

  async function uploadAll() {
    setIsUploading(true);
    try {
      const items = queue.filter(
        (item) => item.status === "waiting" || item.status === "failed",
      );
      for (const item of items) {
        await uploadOne(item);
      }
    } finally {
      setIsUploading(false);
    }
  }

  function clearAll() {
    if (isUploading) {
      return;
    }

    setQueue([]);
    onClear?.();
  }

  function saveDetails() {
    setSaved(true);
    setDetailsOpen(false);
    window.setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="space-y-6">
      <Card className="px-6 py-6">
        <div
          className={cx(
            "flex min-h-[300px] flex-col items-center justify-center rounded-2xl border border-dashed px-8 py-12 text-center transition duration-200",
            dragging ? "border-brand bg-brand-faint" : "border-slate-300 bg-slate-50/50 hover:border-brand/50 hover:bg-brand-faint/30",
          )}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(event) => {
            event.preventDefault();
            setDragging(false);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            addFiles(event.dataTransfer.files);
          }}
        >
          <div className="mb-7 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-faint text-brand shadow-sm ring-1 ring-brand/10">
            <UploadCloud className="h-9 w-9" />
          </div>
          <h2 className="font-display text-[20px] font-bold text-slate-900">{dropTitle}</h2>
          <p className="mt-3 max-w-[520px] text-[15px] leading-6 text-slate-500">
            {helperText}
          </p>
          <input
            accept={accept}
            className="hidden"
            multiple
            onChange={(event) => {
              if (event.target.files) {
                addFiles(event.target.files);
              }
              event.target.value = "";
            }}
            ref={inputRef}
            type="file"
          />
          <Button className="mt-7" onClick={() => inputRef.current?.click()}>
            {browseLabel}
          </Button>
        </div>
        <p className="mt-4 text-center text-[12px] text-slate-400">
          You can upload multiple files at once. Processing runs one file at a time.
        </p>
      </Card>

      {manualDetails ? (
        <Card className="px-6 py-5">
          <button
            className="flex w-full items-center justify-between text-left text-[15px] font-semibold text-slate-900"
            onClick={() => setDetailsOpen((current) => !current)}
            type="button"
          >
            <span>
              Add job details manually{" "}
              <span className="font-normal text-slate-400">(optional)</span>
            </span>
            {detailsOpen ? (
              <ChevronUp className="h-4 w-4 text-slate-400" />
            ) : (
              <ChevronDown className="h-4 w-4 text-brand" />
            )}
          </button>

          {detailsOpen ? (
            <div className="mt-8">
              <p className="mb-5 text-[13px] italic text-slate-400">
                Only needed if you want to override what GPT extracts.
              </p>
              <div className="grid gap-5 sm:grid-cols-2">
                <Input
                  label="Client Name"
                  onChange={(value) => setDetails((current) => ({ ...current, clientName: value }))}
                  placeholder="e.g. TechCorp Inc"
                  value={details.clientName ?? ""}
                />
                <Input
                  label="Location"
                  onChange={(value) => setDetails((current) => ({ ...current, location: value }))}
                  placeholder="e.g. New York, NY"
                  value={details.location ?? ""}
                />
                <Input
                  label="Salary Range"
                  onChange={(value) => setDetails((current) => ({ ...current, salaryRange: value }))}
                  placeholder="e.g. $120k - $160k"
                  value={details.salaryRange ?? ""}
                />
                <Input
                  label="Experience Required"
                  onChange={(value) => setDetails((current) => ({ ...current, experienceRequired: value }))}
                  placeholder="e.g. 5-7 years"
                  value={details.experienceRequired ?? ""}
                />
              </div>
              <div className="mt-6 flex items-center gap-3">
                <Button onClick={saveDetails}>Save Details</Button>
                {saved ? (
                  <span className="text-[13px] font-bold text-[#04743b]">
                    Details saved
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      {queue.length > 0 ? (
        <Card className="px-6 py-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-[20px] font-bold text-slate-900">Selected Files</h2>
            <Badge tone="crimson">{queue.length} files</Badge>
          </div>
          <div className="space-y-3">
            {queue.map((item) => (
              <FileRow
                item={item}
                key={item.id}
                onRemove={() => removeItem(item.id)}
                onRetry={() => uploadOne(item)}
              />
            ))}
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_160px]">
            <Button disabled={isUploading || queue.every((item) => item.status === "processed" || item.status === "duplicate")} isLoading={isUploading} onClick={uploadAll}>
              Upload All
            </Button>
            <Button disabled={isUploading} onClick={clearAll} variant="secondary">
              Clear All
            </Button>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function Input({
  label,
  onChange,
  placeholder,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  placeholder: string;
  value: string;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-[14px] font-semibold text-slate-700">{label}</span>
      <input
        className="field h-10"
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        value={value}
      />
    </label>
  );
}

function FileRow({
  item,
  onRemove,
  onRetry,
}: {
  item: QueueItem;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const canRemove = item.status !== "uploading" && item.status !== "processed";
  const tone =
    item.status === "processed"
      ? "green"
      : item.status === "duplicate"
        ? "amber"
        : item.status === "failed"
          ? "red"
          : "grey";

  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-4 transition hover:border-slate-200 hover:bg-white hover:shadow-sm">
      <div className="flex items-start gap-3">
        <FileText className="mt-1 h-5 w-5 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-[14px] font-semibold text-slate-900">
              {item.file.name}
            </p>
            <span className="text-[12px] text-slate-400">
              {fileSize(item.file.size)}
            </span>
            <Badge tone={tone}>
              {item.status === "processed"
                ? "Processed"
                : item.status === "duplicate"
                  ? "Duplicate"
                  : item.status === "failed"
                    ? "Failed"
                    : item.status === "uploading"
                      ? "Uploading"
                      : "Waiting"}
            </Badge>
          </div>
          {item.status === "duplicate" ? (
            <p className="mt-2 text-[13px] italic text-[#77777a]">
              This file has already been uploaded
            </p>
          ) : null}
          {item.status === "failed" ? (
            <p className="mt-2 text-[13px] font-bold text-[#b91c1c]">
              {item.error ?? "Upload failed"}
            </p>
          ) : null}
          {item.status === "uploading" || item.status === "processed" || item.status === "failed" ? (
            <div className="mt-3">
              <ProgressBar
                className={item.status === "failed" ? "[&>div]:bg-[#dc2626]" : undefined}
                value={item.progress}
              />
              <p className="mt-1 text-[12px] text-[#8b8f97]">
                {item.progress}% complete
              </p>
            </div>
          ) : null}
        </div>
        {item.status === "failed" ? (
          <Button onClick={onRetry} size="sm" variant="secondary">
            Retry
          </Button>
        ) : canRemove ? (
          <button
            className="text-[#a0a4ac] transition hover:text-crimson-700"
            onClick={onRemove}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>
    </div>
  );
}
