"use client";
import React, { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Sparkles, Heart, Image as ImageIcon, ArrowUp, UploadCloud } from "lucide-react";
import "../styles/pixovo-intro.css";

// 10 Curated Photographic Memories that soar upwards like ceremonial balloons
const CEREMONY_BALLOON_PHOTOS = [
  {
    id: 1,
    url: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=400&q=80",
    left: "7%",
    delay: 0.0,
    duration: 4.2,
    tilt: -8,
    scale: 0.95
  },
  {
    id: 2,
    url: "https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&w=400&q=80",
    left: "22%",
    delay: 0.22,
    duration: 4.0,
    tilt: 7,
    scale: 1.05
  },
  {
    id: 3,
    url: "https://images.unsplash.com/photo-1511895426328-dc8714191300?auto=format&fit=crop&w=400&q=80",
    left: "38%",
    delay: 0.44,
    duration: 4.3,
    tilt: -6,
    scale: 0.98
  },
  {
    id: 4,
    url: "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=400&q=80",
    left: "54%",
    delay: 0.18,
    duration: 4.1,
    tilt: 9,
    scale: 1.02
  },
  {
    id: 5,
    url: "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=400&q=80",
    left: "70%",
    delay: 0.4,
    duration: 4.2,
    tilt: -7,
    scale: 0.94
  },
  {
    id: 6,
    url: "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=400&q=80",
    left: "85%",
    delay: 0.12,
    duration: 3.9,
    tilt: 10,
    scale: 1.0
  },
  {
    id: 7,
    url: "https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=400&q=80",
    left: "14%",
    delay: 0.75,
    duration: 4.4,
    tilt: -5,
    scale: 0.92
  },
  {
    id: 8,
    url: "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=400&q=80",
    left: "46%",
    delay: 0.65,
    duration: 4.2,
    tilt: 8,
    scale: 1.06
  },
  {
    id: 9,
    url: "https://images.unsplash.com/photo-1533105079780-92b9be482077?auto=format&fit=crop&w=400&q=80",
    left: "62%",
    delay: 0.9,
    duration: 4.3,
    tilt: -8,
    scale: 0.96
  },
  {
    id: 10,
    url: "https://images.unsplash.com/photo-1511285560929-80b456fea0bc?auto=format&fit=crop&w=400&q=80",
    left: "78%",
    delay: 0.55,
    duration: 4.1,
    tilt: 6,
    scale: 1.0
  }
];

// 4 Clean Occasion Cards from the Reference
const CLEAN_OCCASION_CARDS = [
  {
    id: "trip",
    title: "My last trip",
    image: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=500&q=80",
    prompt: "My last trip — road trips, vacations & scenic adventures"
  },
  {
    id: "gift",
    title: "A heartfelt gift",
    image: "https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=500&q=80",
    prompt: "A heartfelt gift for someone special"
  },
  {
    id: "milestone",
    title: "A big milestone",
    image: "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=500&q=80",
    prompt: "A big milestone celebration — graduations & accomplishments"
  },
  {
    id: "family",
    title: "Family moments",
    image: "https://images.unsplash.com/photo-1511895426328-dc8714191300?auto=format&fit=crop&w=500&q=80",
    prompt: "Family moments — everyday love, reunions & cherished memories"
  }
];

export default function PixovoStoryIntro({
  onSelectOccasion,
  onStorySubmit,
  onTriggerFilePicker,
  dragActive = false,
  isLoading = false
}) {
  // Phase state: 'title' -> 'dissolve' -> 'balloons' -> 'ready'
  const [introStep, setIntroStep] = useState("title");
  const [inputVal, setInputVal] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    // Stage 1: Title holds then dissolves
    const timer1 = setTimeout(() => {
      setIntroStep("dissolve");
    }, 1400);

    // Stage 2: Ceremonial balloon photos launch
    const timer2 = setTimeout(() => {
      setIntroStep("balloons");
    }, 1900);

    // Stage 3: Clean, heartfelt interface appears
    const timer3 = setTimeout(() => {
      setIntroStep("ready");
    }, 3800);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
    };
  }, []);

  const handleSkip = (e) => {
    if (e) e.stopPropagation();
    setIntroStep("ready");
    setTimeout(() => {
      inputRef.current?.focus();
    }, 100);
  };

  const handleFormSubmit = (e) => {
    if (e) e.preventDefault();
    const trimmed = inputVal.trim();
    if (!trimmed || isLoading) return;
    onStorySubmit(trimmed);
  };

  const isBalloonsActive = introStep === "balloons" || introStep === "dissolve";
  const isInterfaceReady = introStep === "ready";

  return (
    <div
      className="pixovo-intro-container"
      onClick={introStep !== "ready" ? handleSkip : undefined}
    >
      {/* Skip button during animation */}
      {introStep !== "ready" && (
        <button
          type="button"
          className="pixovo-intro-skip-btn"
          onClick={handleSkip}
          aria-label="Skip animation to interface"
        >
          Skip intro
        </button>
      )}

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
          STAGE 2: CEREMONIAL BALLOON PHOTOS FLYING UP AND VANISHING
          ================================================================= */}
      {(isBalloonsActive || introStep === "ready") && (
        <div className="pixovo-balloon-stage">
          {CEREMONY_BALLOON_PHOTOS.map((photo) => (
            <motion.div
              key={`balloon-photo-${photo.id}`}
              className="pixovo-balloon-photo"
              style={{
                left: photo.left,
                bottom: "-170px",
                width: "clamp(105px, 11vw, 150px)"
              }}
              initial={{
                y: 0,
                opacity: 0,
                rotate: photo.tilt,
                scale: photo.scale * 0.92
              }}
              animate={
                introStep !== "title"
                  ? {
                      y: "-145vh",
                      x: [0, -18, 22, -14, 16, 0],
                      rotate: [
                        photo.tilt,
                        photo.tilt + 10,
                        photo.tilt - 8,
                        photo.tilt + 6
                      ],
                      opacity: [0, 0.95, 0.95, 0.85, 0],
                      scale: [
                        photo.scale * 0.92,
                        photo.scale,
                        photo.scale * 1.04,
                        photo.scale * 0.94
                      ]
                    }
                  : {}
              }
              transition={{
                duration: photo.duration,
                delay: photo.delay,
                ease: [0.22, 0.1, 0.25, 1],
                times: [0, 0.15, 0.65, 0.88, 1]
              }}
            >
              <div className="pixovo-balloon-polaroid">
                <img
                  src={photo.url}
                  alt="Cherished Memory"
                  className="pixovo-balloon-img"
                  loading="eager"
                />
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* =================================================================
          STAGE 3: CLEAN, HEARTFELT INTERFACE
          ================================================================= */}
      <AnimatePresence>
        {isInterfaceReady && (
          <motion.div
            key="clean-interface-ready"
            className="pixovo-clean-welcome"
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
          >
            {/* Top Brand Logo & Welcome Subtitle */}
            <header className="pixovo-clean-header">
              <div className="pixovo-clean-brand">
                <Heart size={21} className="pixovo-heart-icon" strokeWidth={2.4} />
                <span>pixovo</span>
              </div>
              <p className="pixovo-clean-subline">Welcome to Story Mode</p>
            </header>

            {/* Single Heartfelt Headline */}
            <h1 className="pixovo-clean-title">
              Let’s recreate that moment.
            </h1>

            {/* Curated Occasion Cards */}
            <div className="pixovo-clean-cards-grid">
              {CLEAN_OCCASION_CARDS.map((card) => (
                <button
                  key={card.id}
                  type="button"
                  className="pixovo-clean-card"
                  onClick={() => onSelectOccasion(card)}
                  title={`Start photobook for ${card.title}`}
                >
                  <div className="pixovo-clean-card-img-wrap">
                    <img
                      src={card.image}
                      alt={card.title}
                      className="pixovo-clean-card-img"
                    />
                  </div>
                  <span className="pixovo-clean-card-title">{card.title}</span>
                </button>
              ))}
            </div>

            {/* Almost No Boundary Floating Bottom Input Slot with Ambient Glow */}
            <div className="pixovo-clean-bottom-dock">
              <div className="pixovo-clean-dock-glow" />

              <form className="pixovo-clean-input-bar" onSubmit={handleFormSubmit}>
                <button
                  type="button"
                  className="pixovo-clean-photo-btn"
                  onClick={onTriggerFilePicker}
                  title="Select photos from your device"
                >
                  <ImageIcon size={17} strokeWidth={2.2} color="#0BA28D" />
                  <span>Photos</span>
                </button>

                <input
                  ref={inputRef}
                  type="text"
                  className="pixovo-clean-input"
                  placeholder="Or tell us in your own words..."
                  value={inputVal}
                  onChange={(e) => setInputVal(e.target.value)}
                  disabled={isLoading}
                />

                <button
                  type="submit"
                  className="pixovo-clean-send-btn"
                  disabled={!inputVal.trim() || isLoading}
                  aria-label="Continue with story"
                >
                  <ArrowUp size={18} strokeWidth={2.5} />
                </button>
              </form>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Drag & Drop Visual Overlay when dragging photos over screen */}
      {dragActive && (
        <div className="pixovo-clean-drag-overlay">
          <UploadCloud size={44} color="#0BA28D" strokeWidth={2} />
          <div className="pixovo-clean-drag-text">Drop your photos to begin creating</div>
        </div>
      )}
    </div>
  );
}
