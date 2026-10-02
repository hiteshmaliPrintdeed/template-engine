"use client";
import React, { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Sparkles, Heart, Image as ImageIcon, UploadCloud } from "lucide-react";
import { useToast } from "./Toast";
import "../styles/pixovo-intro.css";

// 10 Curated Photographic Memories that soar upwards like ceremonial balloons
const CEREMONY_BALLOON_PHOTOS = [
  {
    id: 1,
    url: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=400&q=80",
    left: "7%",
    delay: 0.0,
    duration: 3.9,
    tilt: -8,
    scale: 0.95
  },
  {
    id: 2,
    url: "https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&w=400&q=80",
    left: "22%",
    delay: 0.2,
    duration: 3.8,
    tilt: 7,
    scale: 1.05
  },
  {
    id: 3,
    url: "https://images.unsplash.com/photo-1511895426328-dc8714191300?auto=format&fit=crop&w=400&q=80",
    left: "38%",
    delay: 0.4,
    duration: 4.0,
    tilt: -6,
    scale: 0.98
  },
  {
    id: 4,
    url: "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=400&q=80",
    left: "54%",
    delay: 0.15,
    duration: 3.9,
    tilt: 9,
    scale: 1.02
  },
  {
    id: 5,
    url: "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=400&q=80",
    left: "70%",
    delay: 0.35,
    duration: 4.0,
    tilt: -7,
    scale: 0.94
  },
  {
    id: 6,
    url: "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=400&q=80",
    left: "85%",
    delay: 0.1,
    duration: 3.7,
    tilt: 10,
    scale: 1.0
  },
  {
    id: 7,
    url: "https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=400&q=80",
    left: "14%",
    delay: 0.65,
    duration: 3.9,
    tilt: -5,
    scale: 0.92
  },
  {
    id: 8,
    url: "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=400&q=80",
    left: "46%",
    delay: 0.55,
    duration: 3.9,
    tilt: 8,
    scale: 1.06
  },
  {
    id: 9,
    url: "https://images.unsplash.com/photo-1533105079780-92b9be482077?auto=format&fit=crop&w=400&q=80",
    left: "62%",
    delay: 0.75,
    duration: 4.0,
    tilt: -8,
    scale: 0.96
  },
  {
    id: 10,
    url: "https://images.unsplash.com/photo-1511285560929-80b456fea0bc?auto=format&fit=crop&w=400&q=80",
    left: "78%",
    delay: 0.45,
    duration: 3.8,
    tilt: 6,
    scale: 1.0
  }
];

export default function PixovoStoryIntro({
  onPhotosSelected,
  onReadyForChat,
  isLoading = false
}) {
  const toast = useToast();
  // Phase state: 'title' -> 'dissolve' -> 'upload_prompt' -> 'balloons'
  const [introStep, setIntroStep] = useState("title");
  const [isDragOver, setIsDragOver] = useState(false);
  const [balloonPhotos, setBalloonPhotos] = useState(CEREMONY_BALLOON_PHOTOS);
  const fileInputRef = useRef(null);
  const userUrlsRef = useRef([]);
  const pendingFilesRef = useRef(null);
  const balloonTimerRef = useRef(null);

  useEffect(() => {
    // Stage 1: Title holds for 1.2s then dissolves
    const timer1 = setTimeout(() => {
      setIntroStep("dissolve");
    }, 1200);

    // Stage 2: Reveal the clean circular upload prompt with headline and instructions
    const timer2 = setTimeout(() => {
      setIntroStep("upload_prompt");
    }, 1850);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
    };
  }, []);

  // Cleanup any created object URLs and pending animation timers on unmount
  useEffect(() => {
    return () => {
      if (balloonTimerRef.current) {
        clearTimeout(balloonTimerRef.current);
      }
      userUrlsRef.current.forEach((url) => {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // ignore
        }
      });
    };
  }, []);

  const handleProcessUploadedFiles = (files) => {
    if (!files || files.length === 0) return;
    const fileList = Array.from(files);
    const imageFiles = fileList.filter((f) =>
      f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|gif)$/i.test(f.name)
    );

    if (imageFiles.length === 0) {
      toast.show({
        title: "No photos found",
        message: "Please drop or select valid image files (JPEG, PNG, WebP, or HEIC).",
        tone: "warning"
      });
      return;
    }

    // Create local object URLs for the flying balloon ceremony
    const newUrls = imageFiles.map((file) => URL.createObjectURL(file));
    userUrlsRef.current.push(...newUrls);

    const customBalloons = CEREMONY_BALLOON_PHOTOS.map((balloon, idx) => {
      if (idx < newUrls.length) {
        return {
          ...balloon,
          url: newUrls[idx % newUrls.length]
        };
      }
      return balloon;
    });

    setBalloonPhotos(customBalloons);

    // Store files to start uploading ONLY AFTER the balloon animation concludes
    pendingFilesRef.current = imageFiles;

    // Launch ceremonial balloon flight immediately
    setIntroStep("balloons");

    // Once the balloon animation completes smoothly, start upload and reveal chat
    if (balloonTimerRef.current) {
      clearTimeout(balloonTimerRef.current);
    }
    balloonTimerRef.current = setTimeout(() => {
      // 1. Trigger the photo upload / downsampling pipeline
      if (onPhotosSelected && pendingFilesRef.current) {
        onPhotosSelected(pendingFilesRef.current);
      }
      // 2. Transition into the chatting interface
      if (onReadyForChat) {
        onReadyForChat();
      }
    }, 4600);
  };

  const handleFileInputChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleProcessUploadedFiles(e.target.files);
      e.target.value = "";
    }
  };

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleProcessUploadedFiles(e.dataTransfer.files);
    }
  };

  return (
    <div
      className="pixovo-intro-container"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Hidden file input triggered by dragzone or select button */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/*"
        style={{ display: "none" }}
        onChange={handleFileInputChange}
        disabled={isLoading}
      />

      {/* =================================================================
          STAGE 1: "PIXOVO STORY MODE" TITLE FADE UP & ZOOM DISSOLVE
          ================================================================= */}
      <AnimatePresence>
        {(introStep === "title" || introStep === "dissolve") && (
          <motion.div
            key="intro-title-stage"
            className="pixovo-intro-title-wrapper"
            initial={{ opacity: 0, y: 32, scale: 0.96 }}
            animate={
              introStep === "title"
                ? { opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }
                : { opacity: 0, y: -24, scale: 1.35, filter: "blur(18px)" }
            }
            exit={{ opacity: 0, scale: 1.4, filter: "blur(20px)" }}
            transition={
              introStep === "title"
                ? { duration: 0.85, ease: [0.16, 1, 0.3, 1] }
                : { duration: 0.75, ease: [0.33, 1, 0.68, 1] }
            }
          >
            <div className="pixovo-intro-eyebrow">
              <Sparkles size={15} strokeWidth={2.4} color="#0BA28D" />
              <span>AI Story Studio</span>
            </div>
            <h1 className="pixovo-intro-title">Pixovo Story Mode</h1>
          </motion.div>
        )}
      </AnimatePresence>

      {/* =================================================================
          STAGE 2: BRAND, HEADLINE, CIRCULAR DRAG & DROP & INSTRUCTIONS
          ================================================================= */}
      <AnimatePresence>
        {introStep === "upload_prompt" && (
          <motion.div
            key="upload-prompt-phase"
            className="pixovo-upload-phase-wrap"
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.65, ease: [0.16, 1, 0.3, 1] }}
          >
            {/* Top: Brand & Welcome Subline */}
            <header className="pixovo-clean-header">
              <div className="pixovo-clean-brand">
                <Heart size={21} className="pixovo-heart-icon" strokeWidth={2.4} />
                <span>pixovo</span>
              </div>
              <p className="pixovo-clean-subline">Welcome to Story Mode</p>
            </header>

            {/* Headline */}
            <h1 className="pixovo-clean-title">
              Let’s recreate that moment.
            </h1>

            {/* Middle: Circular Drag & Drop or Select Option for Photos */}
            <div
              className={`pixovo-upload-dropzone ${isDragOver ? "is-dragover" : ""}`}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  fileInputRef.current?.click();
                }
              }}
              title="Click or drag photos here to upload"
            >
              <div className="pixovo-upload-icon-circle">
                <UploadCloud size={24} strokeWidth={2.2} />
              </div>

              <div className="pixovo-upload-text-group">
                <h3 className="pixovo-upload-heading">Drag & drop photos</h3>
                <p className="pixovo-upload-subheading">or click anywhere to browse</p>
              </div>

              <button
                type="button"
                className="pixovo-upload-cta-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  fileInputRef.current?.click();
                }}
              >
                <ImageIcon size={15} strokeWidth={2.2} />
                <span>Select Photos</span>
              </button>
            </div>

            {/* Bottom: Instructions */}
            <div className="pixovo-upload-instructions-box">
              <div className="pixovo-instruction-pill">
                <span className="pixovo-instruction-badge">15–80 Photos</span>
                <span className="pixovo-instruction-desc">
                  Ideal for a balanced, full-spread keepsake book
                </span>
              </div>
              <div className="pixovo-instruction-pill">
                <span className="pixovo-instruction-badge">JPG • PNG • HEIC</span>
                <span className="pixovo-instruction-desc">
                  Works directly with camera & phone files
                </span>
              </div>
              <div className="pixovo-instruction-pill">
                <span className="pixovo-instruction-badge">Auto Curated</span>
                <span className="pixovo-instruction-desc">
                  Smart AI filters duplicates & orders key moments
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* =================================================================
          STAGE 3: CEREMONIAL BALLOON PHOTOS FLYING UP AND VANISHING
          ================================================================= */}
      {introStep === "balloons" && (
        <div className="pixovo-balloon-stage">

          {balloonPhotos.map((photo) => (
            <motion.div
              key={`balloon-photo-${photo.id}`}
              className="pixovo-balloon-photo"
              style={{
                left: photo.left,
                bottom: "-210px",
                width: "clamp(115px, 11vw, 155px)"
              }}
              initial={{
                y: 0,
                x: 0,
                opacity: 0,
                rotate: photo.tilt,
                scale: photo.scale * 0.94
              }}
              animate={{
                y: "-145vh",
                x: [0, photo.tilt > 0 ? 12 : -12, photo.tilt > 0 ? -10 : 10, 0],
                rotate: [
                  photo.tilt,
                  photo.tilt + (photo.tilt > 0 ? 4 : -4),
                  photo.tilt - (photo.tilt > 0 ? 2 : -2),
                  photo.tilt
                ],
                scale: [
                  photo.scale * 0.94,
                  photo.scale,
                  photo.scale * 1.02,
                  photo.scale * 0.96
                ],
                opacity: [0, 1, 1, 0.85, 0]
              }}
              transition={{
                duration: photo.duration,
                delay: photo.delay,
                ease: "easeInOut",
                times: [0, 0.15, 0.55, 0.82, 1],
                y: {
                  duration: photo.duration,
                  delay: photo.delay,
                  ease: [0.25, 0.1, 0.25, 1]
                }
              }}
            >
              <div className="pixovo-balloon-polaroid">
                <img
                  src={photo.url}
                  alt="Cherished Memory"
                  className="pixovo-balloon-img"
                  loading="eager"
                  decoding="async"
                />
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
