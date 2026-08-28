import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

interface UploadClientPayload {
  interviewToken: string;
  questionIndex: number;
}

interface UploadIntent {
  upload_mode: "direct_blob" | "multipart";
  question_index: number;
  pathname: string;
  maximum_size_bytes: number;
}

function backendUrl(request: Request, path: string) {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim() || "/api/backend";
  const base = new URL(configured.endsWith("/") ? configured : `${configured}/`, request.url);
  return new URL(path.replace(/^\//, ""), base);
}

export async function POST(request: Request) {
  let body: HandleUploadBody;
  try {
    body = (await request.json()) as HandleUploadBody;
  } catch {
    return NextResponse.json({ error: "Invalid upload request" }, { status: 400 });
  }

  try {
    const response = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        let payload: UploadClientPayload;
        try {
          payload = JSON.parse(clientPayload || "") as UploadClientPayload;
        } catch {
          throw new Error("Invalid interview upload authorization");
        }
        if (
          !payload.interviewToken ||
          !Number.isInteger(payload.questionIndex) ||
          payload.questionIndex < 0
        ) {
          throw new Error("Invalid interview upload authorization");
        }

        const authorizationResponse = await fetch(
          backendUrl(
            request,
            `interviews/${encodeURIComponent(payload.interviewToken)}/video-upload-intent`,
          ),
          { method: "POST", cache: "no-store" },
        );
        if (!authorizationResponse.ok) {
          throw new Error("Interview upload is not authorized");
        }
        const intent = (await authorizationResponse.json()) as UploadIntent;
        if (
          intent.upload_mode !== "direct_blob" ||
          intent.question_index !== payload.questionIndex ||
          intent.pathname !== pathname
        ) {
          throw new Error("Interview upload authorization did not match the request");
        }

        return {
          allowedContentTypes: ["video/webm"],
          maximumSizeInBytes: intent.maximum_size_bytes,
          validUntil: Date.now() + 5 * 60 * 1000,
          addRandomSuffix: true,
          allowOverwrite: false,
        };
      },
      onUploadCompleted: async () => {
        // The candidate confirms the returned private pathname with FastAPI.
        // No database state changes from this callback.
      },
    });
    return NextResponse.json(response);
  } catch (error) {
    console.error("[interview-video-upload] Token exchange failed", {
      errorType: error instanceof Error ? error.name : "UnknownError",
    });
    return NextResponse.json({ error: "Video upload could not be authorized" }, { status: 400 });
  }
}
