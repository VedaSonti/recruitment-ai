"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactEventHandler,
  type ReactNode,
  type RefCallback,
} from "react";
import { useParams } from "next/navigation";
import { upload } from "@vercel/blob/client";
import {
  AlertCircle,
  Camera,
  CheckCircle,
  Loader2,
  Mic,
  Video,
  Volume2,
} from "lucide-react";
import { PersonaLogo } from "@/components/branding/PersonaLogo";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL?.trim() || "/api/backend";
const MAX_RECORDING_SECONDS = 30;
const VIDEO_FRAME_TIMEOUT_MS = 5000;
const VIDEO_MIME_TYPES = [
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
];
const VIDEO_CONSTRAINTS: MediaStreamConstraints = {
  video: true,
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
type QuestionAudioStatus = "idle" | "loading" | "playing" | "error";
type RecordingStartTrigger = "audio-ended" | "manual-fallback";

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

interface VideoUploadIntent {
  upload_mode: "direct_blob" | "multipart";
  question_index: number;
  pathname: string;
  maximum_size_bytes: number;
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

function logMediaTrackStatus(stream: MediaStream) {
  stream.getTracks().forEach((track) => {
    console.info("[camera] Track status", {
      kind: track.kind,
      label: track.label,
      enabled: track.enabled,
      muted: track.muted,
      readyState: track.readyState,
    });
  });
}

function clearQuestionAudioHandlers(audio: HTMLAudioElement) {
  audio.onloadstart = null;
  audio.onloadedmetadata = null;
  audio.oncanplay = null;
  audio.onplay = null;
  audio.onplaying = null;
  audio.onvolumechange = null;
  audio.onended = null;
  audio.onpause = null;
  audio.onerror = null;
  audio.onabort = null;
  audio.onstalled = null;
}

function mediaLogTime() {
  return {
    timestamp: new Date().toISOString(),
    performanceMs: Math.round(performance.now()),
  };
}

function waitForVideoFrames(
  videoElement: HTMLVideoElement,
  stream: MediaStream,
): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false;

    const cleanup = () => {
      window.clearTimeout(timeoutId);
      frameEvents.forEach((eventName) => {
        videoElement.removeEventListener(eventName, handleFrameEvent);
      });
      videoElement.removeEventListener("error", handleFatalEvent);
      videoElement.removeEventListener("stalled", handleFatalEvent);
    };

    const hasVisibleFrames = () => {
      const videoTrack = stream.getVideoTracks()[0];
      return (
        stream.active &&
        Boolean(videoTrack) &&
        videoTrack.readyState === "live" &&
        videoElement.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
        videoElement.videoWidth > 0 &&
        videoElement.videoHeight > 0
      );
    };

    const finish = (callback: () => void) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      callback();
    };

    const handleFrameEvent = () => {
      if (hasVisibleFrames()) {
        finish(resolve);
      }
    };

    const handleFatalEvent = (event: Event) => {
      const mediaError = videoElement.error;
      finish(() => {
        reject(
          new Error(
            mediaError
              ? `Camera preview failed with media error code ${mediaError.code}.`
              : `Camera preview emitted a ${event.type} event before frames were available.`,
          ),
        );
      });
    };

    const frameEvents = ["loadedmetadata", "loadeddata", "canplay", "playing"] as const;
    frameEvents.forEach((eventName) => {
      videoElement.addEventListener(eventName, handleFrameEvent);
    });
    videoElement.addEventListener("error", handleFatalEvent);
    videoElement.addEventListener("stalled", handleFatalEvent);

    const timeoutId = window.setTimeout(() => {
      finish(() => {
        reject(new Error("Camera preview did not produce visible frames within 5 seconds."));
      });
    }, VIDEO_FRAME_TIMEOUT_MS);

    handleFrameEvent();
  });
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
  const [questionAudioError, setQuestionAudioError] = useState("");
  const [questionAudioStatus, setQuestionAudioStatus] =
    useState<QuestionAudioStatus>("idle");
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [hasConsent, setHasConsent] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const questionAudioObjectUrlRef = useRef<string | null>(null);
  const audioSessionIdRef = useRef(0);
  const audioPlaybackCompletedSessionRef = useRef<number | null>(null);
  const manualAudioFallbackSessionRef = useRef<number | null>(null);
  const recordingStartRequestedRef = useRef(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mediaRequestRef = useRef<Promise<MediaStream> | null>(null);
  const videoAttachmentIdRef = useRef(0);
  const isMountedRef = useRef(true);

  const attachStreamToVideo = useCallback(async (stream: MediaStream | null) => {
    const attachmentId = ++videoAttachmentIdRef.current;
    const videoElement = videoRef.current;
    if (!videoElement) {
      if (stream) {
        throw new Error("Camera preview element is not mounted.");
      }
      return;
    }

    if (!stream) {
      videoElement.srcObject = null;
      return;
    }

    const videoTrack = stream.getVideoTracks()[0];
    if (!stream.active || !videoTrack || videoTrack.readyState !== "live") {
      throw new Error("Camera stream does not contain an active live video track.");
    }

    if (videoElement.srcObject !== stream) {
      videoRef.current!.srcObject = stream;
      console.info("[camera] MediaStream attached to preview element");
    }

    if (videoElement.paused) {
      await videoElement.play();
      console.info("[camera] Live preview playback started");
    }

    try {
      await waitForVideoFrames(videoElement, stream);
    } catch (frameError) {
      if (attachmentId !== videoAttachmentIdRef.current) {
        return;
      }
      throw frameError;
    }

    if (
      attachmentId !== videoAttachmentIdRef.current ||
      videoRef.current !== videoElement ||
      videoElement.srcObject !== stream
    ) {
      return;
    }

    console.info("[camera] Live preview frames confirmed", {
      readyState: videoElement.readyState,
      width: videoElement.videoWidth,
      height: videoElement.videoHeight,
      trackState: videoTrack.readyState,
    });
    setCameraError("");
    setCameraStatus("ready");
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopStream = useCallback((reason = "camera disabled") => {
    const stream = streamRef.current;
    if (stream) {
      console.info(`[camera] Stopping media tracks: ${reason}`);
      stream.getTracks().forEach((track) => track.stop());
    }
    streamRef.current = null;
    void attachStreamToVideo(null);
    if (isMountedRef.current) {
      setCameraStatus("idle");
    }
  }, [attachStreamToVideo]);

  const releaseQuestionAudio = useCallback((reason: string) => {
    const audio = audioRef.current;
    if (audio) {
      console.info("[question-audio] Releasing Audio element", {
        reason,
        ...mediaLogTime(),
      });
      clearQuestionAudioHandlers(audio);
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      audioRef.current = null;
    }

    const objectUrl = questionAudioObjectUrlRef.current;
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      questionAudioObjectUrlRef.current = null;
      console.info("[question-audio] Revoked MP3 object URL", {
        reason,
        ...mediaLogTime(),
      });
    }
  }, []);

  const handleCameraAttachmentError = useCallback(
    (attachmentError: unknown, context: string) => {
      console.error(`[camera] ${context}`, attachmentError);
      stopStream("fatal camera preview error");
      if (isMountedRef.current) {
        setCameraStatus("error");
        setCameraError(
          attachmentError instanceof Error && attachmentError.message
            ? attachmentError.message
            : "The camera stream started, but visible preview frames were not available.",
        );
      }
    },
    [stopStream],
  );

  const setVideoElement = useCallback<RefCallback<HTMLVideoElement>>(
    (element) => {
      const previousElement = videoRef.current;
      videoAttachmentIdRef.current += 1;
      videoRef.current = element;

      if (!element) {
        if (previousElement) {
          previousElement.srcObject = null;
        }
        return;
      }

      const stream = streamRef.current;
      if (stream) {
        setCameraStatus("checking");
        setCameraError("");
        void attachStreamToVideo(stream).catch((attachmentError) => {
          handleCameraAttachmentError(
            attachmentError,
            "Failed to attach the existing MediaStream to the new preview element.",
          );
        });
      }
    },
    [attachStreamToVideo, handleCameraAttachmentError],
  );

  const ensureMediaStream = useCallback(async () => {
    if (isStreamUsable(streamRef.current)) {
      await attachStreamToVideo(streamRef.current);
      return streamRef.current as MediaStream;
    }

    if (mediaRequestRef.current) {
      return mediaRequestRef.current;
    }

    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void attachStreamToVideo(null);
    setCameraStatus("checking");
    setCameraError("");

    console.info("[camera] Requesting camera and microphone permission", {
      constraints: VIDEO_CONSTRAINTS,
      ...mediaLogTime(),
    });
    const request = navigator.mediaDevices.getUserMedia(VIDEO_CONSTRAINTS);
    mediaRequestRef.current = request;

    try {
      const stream = await request;
      console.info("[camera] MediaStream received", {
        id: stream.id,
        videoTracks: stream.getVideoTracks().length,
        audioTracks: stream.getAudioTracks().length,
        ...mediaLogTime(),
      });
      logMediaTrackStatus(stream);

      if (!isMountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        throw new Error("The camera request completed after leaving the interview page.");
      }

      streamRef.current = stream;
      await attachStreamToVideo(stream);
      return stream;
    } catch (accessError) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      void attachStreamToVideo(null);
      const message = getMediaAccessErrorMessage(accessError);
      if (isMountedRef.current) {
        setCameraStatus("error");
        setCameraError(message);
      }
      console.error("[camera] Camera and microphone setup failed", accessError);
      throw new Error(message);
    } finally {
      mediaRequestRef.current = null;
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
    const stream = streamRef.current;
    if (!stream) {
      return;
    }

    void attachStreamToVideo(stream).catch((attachmentError) => {
      handleCameraAttachmentError(
        attachmentError,
        `Failed to restore the camera preview during the "${phase}" phase.`,
      );
    });
  }, [attachStreamToVideo, handleCameraAttachmentError, phase]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      stopTimer();
      stopStream("leaving interview page");
      releaseQuestionAudio("leaving interview page");
    };
  }, [releaseQuestionAudio, stopStream, stopTimer]);

  const submitRecording = useCallback(
    async (blob: Blob) => {
      if (!token) {
        return;
      }

      setPhase("processing");
      try {
        const intentResponse = await fetch(
          `${BASE_URL}/interviews/${encodeURIComponent(token)}/video-upload-intent`,
          { method: "POST" },
        );
        if (!intentResponse.ok) {
          throw new Error(`Upload intent status ${intentResponse.status}`);
        }
        const intent = (await intentResponse.json()) as VideoUploadIntent;
        if (blob.size <= 0 || blob.size > intent.maximum_size_bytes) {
          throw new Error("Recorded video exceeds the allowed upload size");
        }

        let responseEndpoint = `${BASE_URL}/interviews/${encodeURIComponent(token)}/respond-video`;
        let videoReference: Record<string, string | number> | null = null;
        if (intent.upload_mode === "direct_blob") {
          const webmBlob = new Blob([blob], { type: "video/webm" });
          const storedVideo = await upload(intent.pathname, webmBlob, {
            access: "private",
            handleUploadUrl: "/api/interview-video-upload",
            clientPayload: JSON.stringify({
              interviewToken: token,
              questionIndex: intent.question_index,
            }),
          });
          videoReference = {
            video_storage_key: storedVideo.pathname,
            video_size_bytes: webmBlob.size,
            video_content_type: "video/webm",
          };
          responseEndpoint = `${BASE_URL}/interviews/${encodeURIComponent(token)}/respond-video-reference`;
        }

        for (let attempt = 1; attempt <= 3; attempt += 1) {
          const requestOptions: RequestInit = videoReference
            ? {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(videoReference),
              }
            : (() => {
                const formData = new FormData();
                formData.append("video", blob, "answer.webm");
                return { method: "POST", body: formData };
              })();
          try {
            const response = await fetch(responseEndpoint, requestOptions);
            if (!response.ok) {
              throw new Error(`Status ${response.status}`);
            }

            const data = (await response.json()) as RespondResult;
            if (data.completed) {
              fetch(`${BASE_URL}/interviews/${encodeURIComponent(token)}/assess-video`, {
                method: "POST",
              }).catch(() => undefined);
              stopStream("interview completed");
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
              throw new Error("Video processing request failed");
            }
          }
        }
      } catch (submissionError) {
        console.error("[interview-video] Submission failed", {
          errorType: submissionError instanceof Error ? submissionError.name : "UnknownError",
        });
        setError("Failed to submit your video answer. Please check your connection and try again.");
        setPhase("error");
      }
    },
    [currentIndex, stopStream, token],
  );

  const stopRecording = useCallback(() => {
    stopTimer();

    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      return;
    }

    recorder.onstop = () => {
      const mimeType = recorder.mimeType || getPreferredVideoMimeType() || "video/webm";
      const blob = new Blob(chunksRef.current, { type: mimeType });
      mediaRecorderRef.current = null;
      submitRecording(blob);
    };

    recorder.stop();
  }, [stopTimer, submitRecording]);

  const startRecording = useCallback(async (
    trigger: RecordingStartTrigger,
    audioSessionId: number,
  ) => {
    if (audioSessionId !== audioSessionIdRef.current) {
      console.warn("[recording] Ignoring stale recording request", {
        audioSessionId,
        currentAudioSessionId: audioSessionIdRef.current,
        trigger,
        ...mediaLogTime(),
      });
      return;
    }

    const playbackCompleted =
      audioPlaybackCompletedSessionRef.current === audioSessionId;
    const manualFallbackSelected =
      trigger === "manual-fallback" &&
      manualAudioFallbackSessionRef.current === audioSessionId;

    if (!playbackCompleted && !manualFallbackSelected) {
      const sequencingError = new Error(
        "MediaRecorder start was requested before the current question audio ended.",
      );
      console.error("[recording] Blocked early recording start", {
        audioSessionId,
        trigger,
        playbackCompleted,
        manualFallbackSelected,
        ...mediaLogTime(),
      });
      if (process.env.NODE_ENV !== "production") {
        throw sequencingError;
      }
      return;
    }

    if (recordingStartRequestedRef.current) {
      console.warn("[recording] Ignoring duplicate recording request", {
        audioSessionId,
        trigger,
        ...mediaLogTime(),
      });
      return;
    }

    const existingRecorder = mediaRecorderRef.current;
    if (existingRecorder && existingRecorder.state !== "inactive") {
      console.error("[recording] Refusing to replace an active MediaRecorder", {
        audioSessionId,
        recorderState: existingRecorder.state,
        trigger,
        ...mediaLogTime(),
      });
      return;
    }

    if (timerRef.current) {
      console.error("[recording] Refusing to start while the recording timer is active", {
        audioSessionId,
        trigger,
        ...mediaLogTime(),
      });
      return;
    }

    recordingStartRequestedRef.current = true;
    console.info("[recording] start requested", {
      audioSessionId,
      trigger,
      ...mediaLogTime(),
    });

    try {
      const stream = await ensureMediaStream();

      if (
        audioSessionId !== audioSessionIdRef.current ||
        !recordingStartRequestedRef.current
      ) {
        console.warn("[recording] Recording request became stale during media setup", {
          audioSessionId,
          currentAudioSessionId: audioSessionIdRef.current,
          ...mediaLogTime(),
        });
        return;
      }

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
        stopStream("fatal MediaRecorder error");
        setError("Video recording failed. Please refresh and try the interview again.");
        setPhase("error");
      };

      recorder.start();
      console.info("[recording] MediaRecorder started", {
        audioSessionId,
        mimeType: recorder.mimeType,
        state: recorder.state,
        streamId: stream.id,
        ...mediaLogTime(),
      });
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
      recordingStartRequestedRef.current = false;
      stopTimer();
      stopStream("fatal recording setup error");
      setError(getMediaAccessErrorMessage(accessError));
      setPhase("error");
    }
  }, [ensureMediaStream, stopRecording, stopStream, stopTimer]);

  const playQuestion = useCallback(
    async (index: number) => {
      const audioSessionId = ++audioSessionIdRef.current;
      audioPlaybackCompletedSessionRef.current = null;
      manualAudioFallbackSessionRef.current = null;
      recordingStartRequestedRef.current = false;

      if (!token) {
        return;
      }

      const recorder = mediaRecorderRef.current;
      if (
        (recorder && recorder.state !== "inactive") ||
        timerRef.current
      ) {
        console.error("[question-audio] Refusing to play while recording is active", {
          audioSessionId,
          recorderState: recorder?.state ?? null,
          timerActive: Boolean(timerRef.current),
          ...mediaLogTime(),
        });
        return;
      }

      try {
        if (!isStreamUsable(streamRef.current)) {
          await ensureMediaStream();
        }
      } catch (accessError) {
        stopStream("fatal camera setup error");
        setError(getMediaAccessErrorMessage(accessError));
        setPhase("error");
        return;
      }

      setPhase("playing");
      setQuestionAudioError("");
      setQuestionAudioStatus("loading");
      releaseQuestionAudio("starting or replaying a question");

      const audioUrl =
        `${BASE_URL}/interviews/${encodeURIComponent(token)}/question-audio/${index}`;
      console.info("[question-audio] fetch started", {
        audioSessionId,
        index,
        url: audioUrl,
        ...mediaLogTime(),
      });

      let response: Response;
      let audioBlob: Blob;
      try {
        response = await fetch(audioUrl);
        audioBlob = await response.blob();

        if (audioSessionId !== audioSessionIdRef.current) {
          console.info("[question-audio] Ignoring stale fetch completion", {
            audioSessionId,
            currentAudioSessionId: audioSessionIdRef.current,
            index,
            ...mediaLogTime(),
          });
          return;
        }

        console.info("[question-audio] fetch completed", {
          audioSessionId,
          index,
          url: audioUrl,
          status: response.status,
          ok: response.ok,
          contentType: response.headers.get("content-type"),
          contentLength: response.headers.get("content-length"),
          blobType: audioBlob.type,
          blobSize: audioBlob.size,
          ...mediaLogTime(),
        });

        if (!response.ok) {
          throw new Error(`Question audio request failed with status ${response.status}.`);
        }
        if (audioBlob.size === 0) {
          throw new Error("Question audio response was empty.");
        }

        const contentType = response.headers.get("content-type") ?? audioBlob.type;
        if (!contentType.toLowerCase().startsWith("audio/")) {
          throw new Error(
            `Question audio response had unexpected content type "${contentType || "missing"}".`,
          );
        }
      } catch (fetchError) {
        if (audioSessionId !== audioSessionIdRef.current) {
          return;
        }
        console.error("[question-audio] MP3 fetch failed", {
          audioSessionId,
          index,
          url: audioUrl,
          error: fetchError,
          ...mediaLogTime(),
        });
        setQuestionAudioStatus("error");
        setQuestionAudioError(
          "The interview question could not be loaded. Check your connection, then replay the question.",
        );
        return;
      }

      if (
        !isMountedRef.current ||
        audioSessionId !== audioSessionIdRef.current
      ) {
        return;
      }

      const objectUrl = URL.createObjectURL(audioBlob);
      questionAudioObjectUrlRef.current = objectUrl;
      const audio = new Audio();
      audioRef.current = audio;
      audio.preload = "auto";

      const isCurrentAudioSession = () =>
        audioSessionId === audioSessionIdRef.current &&
        audioRef.current === audio;

      const logAudioState = (eventName: string) => {
        console.info(`[question-audio] ${eventName}`, {
          audioSessionId,
          index,
          url: audioUrl,
          muted: audio.muted,
          volume: audio.volume,
          readyState: audio.readyState,
          networkState: audio.networkState,
          currentSrc: audio.currentSrc,
          duration: audio.duration,
          error: audio.error
            ? { code: audio.error.code, message: audio.error.message }
            : null,
          ...mediaLogTime(),
        });
      };

      let playbackFailed = false;
      const handlePlaybackFailure = (playbackError?: unknown) => {
        if (playbackFailed || !isCurrentAudioSession()) {
          return;
        }

        playbackFailed = true;
        const mediaErrorCode = audio.error?.code;
        console.error("[question-audio] Playback failed", {
          audioSessionId,
          error: playbackError,
          mediaErrorCode,
          url: audioUrl,
          ...mediaLogTime(),
        });
        setQuestionAudioStatus("error");
        setQuestionAudioError(
          "The interview question could not be played. Check your speaker volume and connection, then replay the question.",
        );
        releaseQuestionAudio("question playback failed");
      };

      audio.onloadstart = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("loadstart");
      };
      audio.onloadedmetadata = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("loadedmetadata");
        if (!Number.isFinite(audio.duration) || audio.duration <= 0) {
          handlePlaybackFailure(
            new Error(`Question audio duration is invalid: ${audio.duration}.`),
          );
        }
      };
      audio.oncanplay = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("canplay");
      };
      audio.onplay = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("play");
      };
      let playPromiseResolved = false;
      let playingEventReceived = false;
      const logPlayingEventAfterPlayResolution = () => {
        if (
          playPromiseResolved &&
          playingEventReceived &&
          isCurrentAudioSession()
        ) {
          logAudioState("playing event");
          setQuestionAudioStatus("playing");
          playingEventReceived = false;
        }
      };
      audio.onplaying = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        playingEventReceived = true;
        logPlayingEventAfterPlayResolution();
      };
      audio.onvolumechange = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("volumechange");
      };
      audio.onended = () => {
        if (!isCurrentAudioSession()) {
          return;
        }

        logAudioState("ended event");
        audioPlaybackCompletedSessionRef.current = audioSessionId;
        clearQuestionAudioHandlers(audio);
        audio.removeAttribute("src");
        audio.load();
        audioRef.current = null;
        if (questionAudioObjectUrlRef.current === objectUrl) {
          URL.revokeObjectURL(objectUrl);
          questionAudioObjectUrlRef.current = null;
          console.info("[question-audio] Revoked completed MP3 object URL", {
            audioSessionId,
            index,
            ...mediaLogTime(),
          });
        }
        setQuestionAudioStatus("idle");
        setQuestionAudioError("");
        void startRecording("audio-ended", audioSessionId);
      };
      audio.onpause = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("pause");
      };
      audio.onerror = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("error");
        handlePlaybackFailure(audio.error);
      };
      audio.onabort = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("abort");
      };
      audio.onstalled = () => {
        if (!isCurrentAudioSession()) {
          return;
        }
        logAudioState("stalled");
      };

      audio.muted = false;
      audio.volume = 1;
      audio.src = objectUrl;
      audio.load();
      logAudioState("before play()");

      try {
        console.info("[question-audio] play invoked", {
          audioSessionId,
          index,
          url: audioUrl,
          ...mediaLogTime(),
        });
        await audio.play();
        if (!isCurrentAudioSession()) {
          return;
        }
        playPromiseResolved = true;
        console.info("[question-audio] play resolved", {
          audioSessionId,
          index,
          url: audioUrl,
          ...mediaLogTime(),
        });
        logPlayingEventAfterPlayResolution();
      } catch (playbackError) {
        handlePlaybackFailure(playbackError);
      }
    },
    [ensureMediaStream, releaseQuestionAudio, startRecording, stopStream, token],
  );

  const continueWithoutQuestionAudio = useCallback(() => {
    const audioSessionId = audioSessionIdRef.current;
    manualAudioFallbackSessionRef.current = audioSessionId;
    releaseQuestionAudio("candidate chose to continue without question audio");
    console.warn("[question-audio] Candidate chose to continue without question audio", {
      audioSessionId,
      ...mediaLogTime(),
    });
    setQuestionAudioStatus("idle");
    setQuestionAudioError("");
    void startRecording("manual-fallback", audioSessionId);
  }, [releaseQuestionAudio, startRecording]);

  const beginInterview = useCallback(() => {
    console.info("[question-audio] begin clicked", {
      questionIndex: currentIndex,
      ...mediaLogTime(),
    });
    void playQuestion(currentIndex);
  }, [currentIndex, playQuestion]);

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
        <PersonaLogo className="mt-8 w-[180px]" />
      </Screen>
    );
  }

  if (phase === "welcome" && interview) {
    const canBegin = cameraStatus === "ready" && hasConsent;

    return (
      <Screen>
        <div className="w-full max-w-xl rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
          <PersonaLogo className="mb-2 w-[210px] max-w-full" priority />
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
              onLoadedMetadata={(event) => {
                console.info("[camera] Preview metadata loaded", {
                  width: event.currentTarget.videoWidth,
                  height: event.currentTarget.videoHeight,
                  readyState: event.currentTarget.readyState,
                });
              }}
              status={cameraStatus}
              videoRef={setVideoElement}
            />
          </div>

          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Camera and microphone access are required for this video interview.
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-sm text-amber-700">
              Rapid fire round - 30 seconds per question. Answer concisely and clearly.
              Your video answer auto-submits when time runs out.
            </p>
          </div>

          <label className="mt-4 flex items-start gap-3 rounded-lg border border-gray-200 bg-white p-3 text-sm leading-6 text-gray-600">
            <input
              checked={hasConsent}
              className="mt-1 h-4 w-4 accent-[#7B1111]"
              onChange={(event) => setHasConsent(event.target.checked)}
              type="checkbox"
            />
            <span>
              This interview records audio and video for recruiter review and automated transcription.
              Automated processing may generate neutral observations about recording quality, head orientation,
              and possible additional-speaker or overlapping-speech signals. These signals do not determine
              personality, emotion, honesty, protected characteristics, or suitability. A recruiter reviews the
              recording and makes the final decision.
            </span>
          </label>

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
              onClick={beginInterview}
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
    <div className="fixed inset-0 z-50 flex min-h-screen flex-col overflow-y-auto bg-gray-50">
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

          <CameraPreview
            className="shadow-sm"
            error={cameraError}
            onLoadedMetadata={(event) => {
              console.info("[camera] Preview metadata loaded", {
                width: event.currentTarget.videoWidth,
                height: event.currentTarget.videoHeight,
                readyState: event.currentTarget.readyState,
              });
            }}
            status={cameraStatus}
            videoRef={setVideoElement}
          />

          {phase === "playing" ? (
            <div className="flex flex-col items-center gap-3 py-4">
              {questionAudioStatus === "error" ? (
                <AlertCircle className="text-red-500" size={32} />
              ) : (
                <div className="flex h-10 items-end gap-1">
                  {[3, 5, 7, 5, 3, 6, 4, 7, 5, 3].map((height, index) => (
                    <div
                      className="w-1.5 animate-pulse rounded-full bg-[#7B1111]"
                      key={`${height}-${index}`}
                      style={{ height: `${height * 4}px`, animationDelay: `${index * 0.1}s` }}
                    />
                  ))}
                </div>
              )}
              <p
                className={`flex items-center gap-2 ${
                  questionAudioStatus === "error" ? "text-red-600" : "text-gray-500"
                }`}
              >
                <Volume2 size={16} />
                {questionAudioStatus === "loading"
                  ? "Loading the interview question..."
                  : questionAudioStatus === "error"
                    ? questionAudioError
                    : "AI is reading the question..."}
              </p>
              <div className="flex flex-wrap justify-center gap-3">
                <button
                  className="rounded-lg border border-[#7B1111] px-4 py-2 text-sm font-semibold text-[#7B1111] transition hover:bg-[#fff4f4] disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                  disabled={
                    questionAudioStatus === "loading" || questionAudioStatus === "playing"
                  }
                  onClick={() => playQuestion(currentIndex)}
                  type="button"
                >
                  Replay Question
                </button>
                {questionAudioStatus === "error" ? (
                  <button
                    className="rounded-lg bg-[#7B1111] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#6a0f0f]"
                    onClick={continueWithoutQuestionAudio}
                    type="button"
                  >
                    Continue Without Audio
                  </button>
                ) : null}
              </div>
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
  onLoadedMetadata,
  status,
  videoRef,
}: {
  className?: string;
  error?: string;
  onLoadedMetadata: ReactEventHandler<HTMLVideoElement>;
  status: CameraStatus;
  videoRef: RefCallback<HTMLVideoElement>;
}) {
  const showOverlay = status !== "ready";

  return (
    <div className={`relative overflow-hidden rounded-2xl border border-gray-200 bg-gray-950 ${className}`}>
      <video
        autoPlay
        className="aspect-video w-full object-cover"
        muted
        onLoadedMetadata={onLoadedMetadata}
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
    <div className="fixed inset-0 z-50 overflow-y-auto bg-gray-50 p-6">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] flex-col items-center justify-center text-center">
        {children}
      </div>
    </div>
  );
}
