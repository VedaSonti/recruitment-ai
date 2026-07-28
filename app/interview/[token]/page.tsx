"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { useParams } from "next/navigation";
import {
  AlertCircle,
  Camera,
  CheckCircle,
  Loader2,
  Mic,
  Video,
  Volume2,
} from "lucide-react";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const MAX_RECORDING_SECONDS = 30;
const VIDEO_MIME_TYPES = [
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
];
const VIDEO_CONSTRAINTS: MediaStreamConstraints = {
  video: {
    facingMode: "user",
    width: { ideal: 1280 },
    height: { ideal: 720 },
  },
  audio: true,
};

type Phase =
  | "loading"
  | "welcome"
  | "playing"
  | "recording"
  | "processing"
  | "complete"
  | "error"
  | "expired";

type CameraStatus = "idle" | "checking" | "ready" | "error";

interface InterviewData {
  candidate_name: string;
  job_title: string;
  total_questions: number;
  questions_answered: number;
  current_question_index: number;
  current_question: string | null;
  time_per_question_seconds?: number;
  status: string;
  expires_at: string;
}

interface RespondResult {
  completed?: boolean;
  next_question_index?: number;
  next_question?: string | null;
}

function isStreamUsable(stream: MediaStream | null) {
  if (!stream) {
    return false;
  }

  return (
    stream.getVideoTracks().some((track) => track.readyState === "live") &&
    stream.getAudioTracks().some((track) => track.readyState === "live")
  );
}

function getPreferredVideoMimeType() {
  if (typeof MediaRecorder === "undefined") {
    return "";
  }

  return VIDEO_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
}

function createVideoRecorder(stream: MediaStream) {
  if (typeof MediaRecorder === "undefined") {
    throw new Error("Video recording is not supported in this browser.");
  }

  const mimeType = getPreferredVideoMimeType();
  return mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
}

function getMediaAccessErrorMessage(error: unknown) {
  if (error instanceof DOMException) {
    switch (error.name) {
      case "NotAllowedError":
      case "SecurityError":
        return "Camera and microphone permission was denied. Please allow both camera and microphone access, then try again.";
      case "NotFoundError":
      case "DevicesNotFoundError":
        return "No camera or microphone was found. Please connect or enable both devices, then try again.";
      case "NotReadableError":
      case "TrackStartError":
        return "Your camera or microphone is already in use by another app. Please close other apps and try again.";
      case "OverconstrainedError":
        return "Your camera or microphone does not support the required interview settings. Please try another device.";
      default:
        return "Camera and microphone access are required to complete this video interview.";
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Camera and microphone access are required to complete this video interview.";
}

export default function InterviewPage() {
  const { token } = useParams<{ token: string }>();
  const [phase, setPhase] = useState<Phase>("loading");
  const [interview, setInterview] = useState<InterviewData | null>(null);
  const [error, setError] = useState("");
  const [cameraError, setCameraError] = useState("");
  const [cameraStatus, setCameraStatus] = useState<CameraStatus>("idle");
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [currentIndex, setCurrentIndex] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const attachStreamToVideo = useCallback((stream: MediaStream | null) => {
    if (!videoRef.current) {
      return;
    }

    videoRef.current.srcObject = stream;
    if (stream) {
      void videoRef.current.play().catch(() => undefined);
    }
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    attachStreamToVideo(null);
    setCameraStatus("idle");
  }, [attachStreamToVideo]);

  const ensureMediaStream = useCallback(async () => {
    if (isStreamUsable(streamRef.current)) {
      attachStreamToVideo(streamRef.current);
      setCameraStatus("ready");
      setCameraError("");
      return streamRef.current as MediaStream;
    }

    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    attachStreamToVideo(null);
    setCameraStatus("checking");
    setCameraError("");

    try {
      const stream = await navigator.mediaDevices.getUserMedia(VIDEO_CONSTRAINTS);
      streamRef.current = stream;
      attachStreamToVideo(stream);
      setCameraStatus("ready");
      return stream;
    } catch (accessError) {
      streamRef.current = null;
      attachStreamToVideo(null);
      setCameraStatus("error");
      const message = getMediaAccessErrorMessage(accessError);
      setCameraError(message);
      throw new Error(message);
    }
  }, [attachStreamToVideo]);

  const prepareCamera = useCallback(async () => {
    try {
      await ensureMediaStream();
    } catch {
      // Inline camera error is shown in the welcome screen.
    }
  }, [ensureMediaStream]);

  const fetchInterview = useCallback(async () => {
    if (!token) {
      return;
    }

    setPhase("loading");
    setError("");

    try {
      const response = await fetch(`${BASE_URL}/interviews/${encodeURIComponent(token)}`);

      if (response.status === 410) {
        setPhase("expired");
        return;
      }

      if (!response.ok) {
        setError("Interview not found.");
        setPhase("error");
        return;
      }

      const data = (await response.json()) as InterviewData;
      setInterview(data);
      setCurrentIndex(data.current_question_index ?? 0);
      setPhase(data.status === "Completed" ? "complete" : "welcome");
    } catch {
      setError("Could not load interview.");
      setPhase("error");
    }
  }, [token]);

  useEffect(() => {
    fetchInterview();
  }, [fetchInterview]);

  useEffect(() => {
    attachStreamToVideo(streamRef.current);
  }, [attachStreamToVideo, phase]);

  useEffect(() => {
    return () => {
      stopTimer();
      stopStream();
      audioRef.current?.pause();
    };
  }, [stopStream, stopTimer]);

  const submitRecording = useCallback(
    async (blob: Blob) => {
      if (!token) {
        return;
      }

      setPhase("processing");

      for (let attempt = 1; attempt <= 3; attempt += 1) {
        const formData = new FormData();
        formData.append("video", blob, "answer.webm");

        try {
          const response = await fetch(
            `${BASE_URL}/interviews/${encodeURIComponent(token)}/respond-video`,
            {
              method: "POST",
              body: formData,
            },
          );

          if (!response.ok) {
            throw new Error(`Status ${response.status}`);
          }

          const data = (await response.json()) as RespondResult;

          if (data.completed) {
            fetch(`${BASE_URL}/interviews/${encodeURIComponent(token)}/assess-video`, {
              method: "POST",
            }).catch(() => undefined);
            setPhase("complete");
            return;
          }

          const nextIndex = data.next_question_index ?? currentIndex + 1;
          setCurrentIndex(nextIndex);
          setInterview((previous) =>
            previous
              ? {
                  ...previous,
                  current_question_index: nextIndex,
                  current_question: data.next_question ?? previous.current_question,
                  questions_answered: nextIndex,
                }
              : previous,
          );

          window.setTimeout(() => {
            playQuestionRef.current(nextIndex);
          }, 1500);
          return;
        } catch {
          if (attempt === 3) {
            setError("Failed to submit your video answer. Please check your connection and try again.");
            setPhase("error");
          }
        }
      }
    },
    [currentIndex, token],
  );

  const stopRecording = useCallback(() => {
    stopTimer();

    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      stopStream();
      return;
    }

    recorder.onstop = () => {
      const mimeType = recorder.mimeType || getPreferredVideoMimeType() || "video/webm";
      const blob = new Blob(chunksRef.current, { type: mimeType });
      mediaRecorderRef.current = null;
      stopStream();
      submitRecording(blob);
    };

    recorder.stop();
  }, [stopStream, stopTimer, submitRecording]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await ensureMediaStream();
      const recorder = createVideoRecorder(stream);

      chunksRef.current = [];
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        stopTimer();
        stopStream();
        setError("Video recording failed. Please refresh and try the interview again.");
        setPhase("error");
      };

      recorder.start();
      setRecordingSeconds(0);
      setPhase("recording");

      timerRef.current = setInterval(() => {
        setRecordingSeconds((seconds) => {
          if (seconds >= MAX_RECORDING_SECONDS - 1) {
            stopRecording();
            return seconds;
          }

          return seconds + 1;
        });
      }, 1000);
    } catch (accessError) {
      stopTimer();
      stopStream();
      setError(getMediaAccessErrorMessage(accessError));
      setPhase("error");
    }
  }, [ensureMediaStream, stopRecording, stopStream, stopTimer]);

  const playQuestion = useCallback(
    async (index: number) => {
      if (!token) {
        return;
      }

      try {
        await ensureMediaStream();
      } catch (accessError) {
        stopStream();
        setError(getMediaAccessErrorMessage(accessError));
        setPhase("error");
        return;
      }

      setPhase("playing");

      try {
        const audio = new Audio(
          `${BASE_URL}/interviews/${encodeURIComponent(token)}/question-audio/${index}`,
        );
        audioRef.current = audio;
        audio.onended = () => startRecording();
        audio.onerror = () => startRecording();
        await audio.play();
      } catch {
        startRecording();
      }
    },
    [ensureMediaStream, startRecording, stopStream, token],
  );

  const playQuestionRef = useRef(playQuestion);

  useEffect(() => {
    playQuestionRef.current = playQuestion;
  }, [playQuestion]);

  const formatTime = (seconds: number) =>
    `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(
      2,
      "0",
    )}`;

  const totalQuestions = interview?.total_questions ?? 0;
  const progressPct = totalQuestions > 0 ? Math.round((currentIndex / totalQuestions) * 100) : 0;

  if (phase === "loading") {
    return (
      <Screen>
        <Loader2 className="animate-spin text-[#7B1111]" size={40} />
        <p className="mt-4 text-gray-500">Loading your interview...</p>
      </Screen>
    );
  }

  if (phase === "expired") {
    return (
      <Screen>
        <AlertCircle className="text-red-500" size={48} />
        <h2 className="mt-4 text-xl font-semibold text-gray-800">Link Expired</h2>
        <p className="mt-2 max-w-sm text-center text-gray-500">
          This interview link has expired. Please contact the recruitment team to request a new
          invitation.
        </p>
      </Screen>
    );
  }

  if (phase === "error") {
    return (
      <Screen>
        <AlertCircle className="text-red-500" size={48} />
        <h2 className="mt-4 text-xl font-semibold text-gray-800">Something went wrong</h2>
        <p className="mt-2 max-w-sm text-center text-gray-500">{error}</p>
        <button
          className="mt-6 rounded-lg bg-[#7B1111] px-6 py-2 text-white"
          onClick={() => window.location.reload()}
          type="button"
        >
          Try Again
        </button>
      </Screen>
    );
  }

  if (phase === "complete") {
    return (
      <Screen>
        <CheckCircle className="text-green-500" size={64} />
        <h2 className="mt-6 text-2xl font-bold text-gray-800">
          Thank you, {interview?.candidate_name}!
        </h2>
        <p className="mt-3 max-w-md text-center text-gray-500">
          Your interview responses have been submitted successfully. The recruitment team will
          review your answers and be in touch soon.
        </p>
        <p className="mt-8 text-sm text-gray-400">iSOFT Recruitment</p>
      </Screen>
    );
  }

  if (phase === "welcome" && interview) {
    const canBegin = cameraStatus === "ready";

    return (
      <Screen>
        <div className="w-full max-w-xl rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
          <p className="mb-2 text-sm font-semibold uppercase tracking-wider text-[#7B1111]">
            iSOFT Recruitment
          </p>
          <h1 className="text-2xl font-bold text-gray-900">AI Interview</h1>
          <p className="mt-1 text-gray-500">{interview.job_title}</p>

          <div className="mt-6 space-y-2 rounded-xl bg-gray-50 p-4 text-sm text-gray-600">
            <p>
              Welcome, <strong>{interview.candidate_name}</strong>
            </p>
            <p>
              This interview has <strong>{interview.total_questions} questions</strong>.
            </p>
            <p>
              The AI will speak each question aloud. After it finishes, answer on camera and submit
              when you are done.
            </p>
            <p>Each answer has a <strong>30-second limit</strong> - rapid fire round.</p>
            <p>Estimated total time: <strong>{Math.ceil(interview.total_questions * 0.75)} minutes</strong></p>
          </div>

          <div className="mt-5">
            <CameraPreview
              error={cameraError}
              status={cameraStatus}
              videoRef={videoRef}
            />
          </div>

          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Camera and microphone access are required for this video interview.
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-sm text-amber-700">
              Rapid fire round - 30 seconds per question. Answer concisely and clearly.
              Your video answer auto-submits when time runs out.
            </p>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <button
              className="rounded-xl border border-[#7B1111] px-5 py-3 font-semibold text-[#7B1111] transition hover:bg-[#fff4f4] disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
              disabled={cameraStatus === "checking"}
              onClick={prepareCamera}
              type="button"
            >
              {cameraStatus === "checking" ? "Checking camera..." : cameraStatus === "ready" ? "Camera Ready" : "Enable Camera & Mic"}
            </button>
            <button
              className="rounded-xl bg-[#7B1111] px-5 py-3 text-lg font-semibold text-white transition hover:bg-[#6a0f0f] disabled:cursor-not-allowed disabled:bg-gray-300"
              disabled={!canBegin}
              onClick={() => playQuestion(currentIndex)}
              type="button"
            >
              Begin Interview
            </button>
          </div>

          <p className="mt-4 text-center text-xs text-gray-400">
            Link expires {new Date(interview.expires_at).toLocaleDateString()}
          </p>
        </div>
      </Screen>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex min-h-screen flex-col bg-gray-50">
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="mx-auto max-w-2xl">
          <div className="mb-2 flex justify-between text-sm text-gray-500">
            <span>
              Question {currentIndex + 1} of {interview?.total_questions}
            </span>
            <span>{progressPct}% complete</span>
          </div>
          <div className="h-2 rounded-full bg-gray-200">
            <div
              className="h-2 rounded-full bg-[#7B1111] transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </div>

      <div className="flex flex-1 items-center justify-center overflow-y-auto p-6">
        <div className="w-full max-w-2xl space-y-6">
          <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#7B1111]">
              Question {currentIndex + 1}
            </p>
            <p className="text-xl font-medium leading-relaxed text-gray-900">
              {interview?.current_question}
            </p>
          </div>

          <CameraPreview
            className="shadow-sm"
            error={cameraError}
            status={cameraStatus}
            videoRef={videoRef}
          />

          {phase === "playing" ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <div className="flex h-10 items-end gap-1">
                {[3, 5, 7, 5, 3, 6, 4, 7, 5, 3].map((height, index) => (
                  <div
                    className="w-1.5 animate-pulse rounded-full bg-[#7B1111]"
                    key={`${height}-${index}`}
                    style={{ height: `${height * 4}px`, animationDelay: `${index * 0.1}s` }}
                  />
                ))}
              </div>
              <p className="flex items-center gap-2 text-gray-500">
                <Volume2 size={16} /> AI is reading the question...
              </p>
            </div>
          ) : null}

          {phase === "recording" ? (
            <div className="flex flex-col items-center gap-4 py-4">
              <div className="flex h-16 w-16 animate-pulse items-center justify-center rounded-full border-4 border-red-300 bg-red-100">
                <Mic className="text-red-600" size={28} />
              </div>
              <p className="font-medium text-gray-700">Recording video - speak your answer now</p>
              <p
                className={`font-mono text-2xl ${
                  MAX_RECORDING_SECONDS - recordingSeconds <= 10 ? "text-red-600" : "text-gray-900"
                }`}
              >
                {formatTime(MAX_RECORDING_SECONDS - recordingSeconds)}
              </p>
              <div className="h-2 w-full max-w-sm overflow-hidden rounded-full bg-gray-200">
                <div
                  className={`h-2 rounded-full transition-all duration-500 ${
                    MAX_RECORDING_SECONDS - recordingSeconds <= 5
                      ? "bg-red-500"
                      : MAX_RECORDING_SECONDS - recordingSeconds <= 10
                        ? "bg-amber-500"
                        : "bg-[#7B1111]"
                  }`}
                  style={{ width: `${((MAX_RECORDING_SECONDS - recordingSeconds) / MAX_RECORDING_SECONDS) * 100}%` }}
                />
              </div>
              <p className="text-xs text-gray-400">
                30 seconds per video answer - auto-submits when time runs out
              </p>
              <button
                className="rounded-xl bg-[#7B1111] px-8 py-3 font-semibold text-white transition hover:bg-[#6a0f0f]"
                onClick={stopRecording}
                type="button"
              >
                Stop & Submit Answer
              </button>
            </div>
          ) : null}

          {phase === "processing" ? (
            <div className="flex flex-col items-center gap-3 py-6">
              <Loader2 className="animate-spin text-[#7B1111]" size={36} />
              <p className="text-gray-500">Processing your video answer...</p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function CameraPreview({
  className = "",
  error,
  status,
  videoRef,
}: {
  className?: string;
  error?: string;
  status: CameraStatus;
  videoRef: RefObject<HTMLVideoElement>;
}) {
  const showOverlay = status !== "ready";

  return (
    <div className={`relative overflow-hidden rounded-2xl border border-gray-200 bg-gray-950 ${className}`}>
      <video
        autoPlay
        className="aspect-video w-full object-cover"
        muted
        playsInline
        ref={videoRef}
      />
      {showOverlay ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950/85 p-6 text-center text-white">
          {status === "checking" ? (
            <Loader2 className="mb-3 animate-spin text-white" size={32} />
          ) : status === "error" ? (
            <AlertCircle className="mb-3 text-red-300" size={34} />
          ) : (
            <Camera className="mb-3 text-white/80" size={34} />
          )}
          <p className="text-sm font-semibold">
            {status === "checking"
              ? "Checking camera and microphone..."
              : status === "error"
                ? "Camera check failed"
                : "Camera preview will appear here"}
          </p>
          <p className="mt-2 max-w-sm text-xs leading-5 text-white/70">
            {status === "error"
              ? error
              : "Enable your camera and microphone before beginning the interview."}
          </p>
        </div>
      ) : (
        <div className="absolute left-3 top-3 inline-flex items-center gap-2 rounded-full bg-black/55 px-3 py-1 text-xs font-semibold text-white">
          <Video size={14} /> Live preview
        </div>
      )}
    </div>
  );
}

function Screen({ children }: { children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex min-h-screen flex-col items-center justify-center bg-gray-50 p-6">
      <div className="flex flex-col items-center text-center">{children}</div>
    </div>
  );
}
