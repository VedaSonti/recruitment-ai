"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useParams } from "next/navigation";
import {
  AlertCircle,
  CheckCircle,
  Loader2,
  Mic,
  Volume2,
} from "lucide-react";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const MAX_RECORDING_SECONDS = 30;

type Phase =
  | "loading"
  | "welcome"
  | "playing"
  | "recording"
  | "processing"
  | "complete"
  | "error"
  | "expired";

interface InterviewData {
  candidate_name: string;
  job_title: string;
  total_questions: number;
  questions_answered: number;
  current_question_index: number;
  current_question: string | null;
  status: string;
  expires_at: string;
}

interface RespondResult {
  completed?: boolean;
  next_question_index?: number;
  next_question?: string | null;
}

export default function InterviewPage() {
  const { token } = useParams<{ token: string }>();
  const [phase, setPhase] = useState<Phase>("loading");
  const [interview, setInterview] = useState<InterviewData | null>(null);
  const [error, setError] = useState("");
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [currentIndex, setCurrentIndex] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

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

      const formData = new FormData();
      formData.append("audio", blob, "answer.webm");

      for (let attempt = 1; attempt <= 3; attempt += 1) {
        try {
          const response = await fetch(
            `${BASE_URL}/interviews/${encodeURIComponent(token)}/respond`,
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
            fetch(`${BASE_URL}/interviews/${encodeURIComponent(token)}/assess`, {
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
            setError("Failed to submit your answer. Please check your connection and try again.");
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
      return;
    }

    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      stopStream();
      submitRecording(blob);
    };

    recorder.stop();
  }, [stopStream, stopTimer, submitRecording]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const options = MediaRecorder.isTypeSupported("audio/webm")
        ? { mimeType: "audio/webm" }
        : undefined;
      const recorder = new MediaRecorder(stream, options);

      streamRef.current = stream;
      chunksRef.current = [];
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
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
    } catch {
      setError("Microphone access denied. Please enable microphone permissions and reload.");
      setPhase("error");
    }
  }, [stopRecording]);

  const playQuestion = useCallback(
    async (index: number) => {
      if (!token) {
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
    [startRecording, token],
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
    return (
      <Screen>
        <div className="w-full max-w-lg rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
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
              The AI will speak each question aloud. After it finishes, speak your answer and submit
              it when you are done.
            </p>
            <p>Each answer has a <strong>30-second limit</strong> — rapid fire round.</p>
            <p>Estimated total time: <strong>{Math.ceil(interview.total_questions * 0.75)} minutes</strong></p>
          </div>

          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Please ensure your microphone is enabled in your browser before starting.
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-sm text-amber-700">
              ⚡ Rapid fire round — 30 seconds per question. Answer concisely and clearly.
              Your answer auto-submits when time runs out.
            </p>
          </div>

          <button
            className="mt-6 w-full rounded-xl bg-[#7B1111] py-3 text-lg font-semibold text-white transition hover:bg-[#6a0f0f]"
            onClick={() => playQuestion(currentIndex)}
            type="button"
          >
            Begin Interview
          </button>

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

      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-2xl space-y-6">
          <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#7B1111]">
              Question {currentIndex + 1}
            </p>
            <p className="text-xl font-medium leading-relaxed text-gray-900">
              {interview?.current_question}
            </p>
          </div>

          {phase === "playing" ? (
            <div className="flex flex-col items-center gap-3 py-6">
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
            <div className="flex flex-col items-center gap-4 py-6">
              <div className="flex h-24 w-24 animate-pulse items-center justify-center rounded-full border-4 border-red-300 bg-red-100">
                <Mic className="text-red-600" size={36} />
              </div>
              <p className="font-medium text-gray-700">Recording - speak your answer now</p>
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
                30 seconds per answer — auto-submits when time runs out
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
              <p className="text-gray-500">Processing your answer...</p>
            </div>
          ) : null}
        </div>
      </div>
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