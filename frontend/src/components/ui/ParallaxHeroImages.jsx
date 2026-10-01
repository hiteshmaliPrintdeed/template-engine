"use client";
import React, { useEffect, useState, useMemo, useCallback, memo } from "react";
import {
  motion,
  useMotionValue,
  useSpring,
  useTransform,
} from "motion/react";
import { cn } from "@/lib/utils";

const positionStyles = {
  "top-left": { top: "6%", left: "3%" },
  "top-right": { top: "6%", right: "3%" },
  "mid-left": { top: "34%", left: "4%" },
  "mid-right": { top: "34%", right: "4%" },
  "bottom-left": { top: "66%", left: "3%" },
  "bottom-right": { top: "66%", right: "3%" },
  "far-left": { top: "50%", left: "1%" },
  "far-right": { top: "50%", right: "1%" },
};

const positionOrder = [
  "top-left",
  "top-right",
  "mid-left",
  "mid-right",
  "bottom-left",
  "bottom-right",
  "far-left",
  "far-right",
];

const depthValuesByVariant = {
  default: [0.3, 0.35, 0.9, 0.85, 0.4, 0.45, 0.25, 0.2],
  "edge-focus": [0.85, 0.9, 0.3, 0.35, 0.8, 0.85, 0.4, 0.45],
};

const SPRING_CONFIG = { damping: 25, stiffness: 120 };

export const ParallaxHeroImages = ({
  images = [],
  className,
  imageClassName,
  variant = "default",
}) => {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  const smoothMouseX = useSpring(mouseX, SPRING_CONFIG);
  const smoothMouseY = useSpring(mouseY, SPRING_CONFIG);

  const positions = useMemo(() => {
    if (!images || images.length === 0) return [];
    const limitedImages = images.slice(0, 8);
    const depthValues = depthValuesByVariant[variant] || depthValuesByVariant.default;
    return limitedImages.map((src, index) => ({
      src,
      position: positionOrder[index % positionOrder.length],
      depth: depthValues[index % depthValues.length],
      delay: index * 0.12,
    }));
  }, [images, variant]);

  useEffect(() => {
    const handleMouseMove = (e) => {
      const x = (e.clientX / window.innerWidth) * 2 - 1;
      const y = (e.clientY / window.innerHeight) * 2 - 1;
      mouseX.set(x);
      mouseY.set(y);
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [mouseX, mouseY]);

  if (!images || images.length === 0) return null;

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className,
      )}
      style={{ zIndex: 0 }}
    >
      {positions.map((pos, index) => (
        <ParallaxImage
          key={`${pos.src}-${index}`}
          src={pos.src}
          position={pos.position}
          depth={pos.depth}
          delay={pos.delay}
          imageClassName={imageClassName}
          smoothMouseX={smoothMouseX}
          smoothMouseY={smoothMouseY}
        />
      ))}
    </div>
  );
};

const ParallaxImage = memo(function ParallaxImage({
  src,
  position,
  depth,
  delay,
  imageClassName,
  smoothMouseX,
  smoothMouseY,
}) {
  const maxOffset = 40;

  const translateX = useTransform(
    smoothMouseX,
    [-1, 1],
    [-maxOffset * depth, maxOffset * depth],
  );

  const translateY = useTransform(
    smoothMouseY,
    [-1, 1],
    [-maxOffset * depth, maxOffset * depth],
  );

  const posStyle = positionStyles[position] || { top: "50%", left: "50%" };

  return (
    <motion.div
      className="absolute"
      style={{
        position: "absolute",
        top: posStyle.top,
        left: posStyle.left,
        right: posStyle.right,
        x: translateX,
        y: translateY,
        zIndex: Math.round(depth * 10),
      }}
      initial={{ opacity: 0, filter: "blur(16px)", scale: 0.88 }}
      animate={{ opacity: 1, filter: "blur(0px)", scale: 1 }}
      transition={{
        duration: 0.8,
        delay: delay,
        ease: [0.25, 0.1, 0.25, 1],
      }}
    >
      <img
        src={src}
        alt="Photobook memory"
        loading="lazy"
        decoding="async"
        className={cn(
          "aspect-4/3 rounded-2xl object-cover shadow-2xl transition-transform duration-300",
          imageClassName,
        )}
        style={{
          width: "clamp(120px, 14vw, 220px)",
          height: "clamp(85px, 10vw, 155px)",
          borderRadius: "16px",
          objectFit: "cover",
          boxShadow: "0 18px 40px -10px rgba(3, 42, 42, 0.22), 0 2px 8px rgba(0,0,0,0.06)",
          border: "2.5px solid #ffffff",
        }}
      />
    </motion.div>
  );
});

export default ParallaxHeroImages;
