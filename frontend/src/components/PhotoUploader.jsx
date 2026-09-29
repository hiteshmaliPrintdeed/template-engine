import React, { useState } from 'react';
import { UploadCloud, Sparkles, CheckCircle2, Loader2, AlertCircle } from 'lucide-react';
import PixovoClientDownsampler from '../utils/client_downsampler';

/**
 * Phase 1 Ingestion Pipeline Component:
 * - Client-side non-blocking downsampling (512px thumbnails)
 * - Live Stepper & Progress indicator (integrated from Phase 1 specs)
 * - Builds Dual-Payload (Thumbnails + Metadata + Originals)
 * - Passes processed payload to parent for backend ingestion handshake
 */
export default function PhotoUploader({ onPhotosUploaded, isUploading }) {
  const [dragActive, setDragActive] = useState(false);
  const [localPhotos, setLocalPhotos] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStage, setProcessingStage] = useState(''); // 'downsampling' | 'ready' | 'error'
  const [progressStats, setProgressStats] = useState({ completed: 0, total: 0 });

  const downsampler = new PixovoClientDownsampler({
    maxDimension: 512,
    quality: 0.85,
    concurrency: 4
  });

  const handleFiles = async (files) => {
    if (!files || files.length === 0) return;
    const fileList = Array.from(files).filter(f => f.type.startsWith('image/'));

    if (fileList.length === 0) {
      alert("Please upload valid image files (JPG, PNG, WebP).");
      return;
    }

    setIsProcessing(true);
    setProcessingStage('downsampling');
    setProgressStats({ completed: 0, total: fileList.length });

    const downsampleStartTime = performance.now();
    try {
      // 1. Client-Side Non-blocking Batch Downsampling & EXIF extraction
      const processedResults = await downsampler.processBatch(fileList, (completed, total) => {
        setProgressStats({ completed, total });
      });

      if (!processedResults || processedResults.length === 0) {
        throw new Error("No valid photos could be processed.");
      }

      const totalDownsampleTimeMs = performance.now() - downsampleStartTime;

      // 2. Build local preview items for instant UI feedback
      const previewItems = processedResults.map(p => ({
        photo_id: p.photo_id,
        filename: p.filename,
        aspect_ratio: p.aspect_ratio,
        previewUrl: URL.createObjectURL(p.thumbnail_blob),
        originalFile: p.original_file,
        thumbnailBlob: p.thumbnail_blob
      }));

      setLocalPhotos(previewItems);
      setProcessingStage('ready');
      setIsProcessing(false);

      // 3. Hand the processed photos to App.jsx, which opens a session and
      //    uploads them in chunks. The payload is no longer built here: a
      //    single FormData containing every original was a ~8GB request at
      //    1,000 photos. App.jsx now calls downsampler.buildChunkPayload()
      //    once per chunk.
      onPhotosUploaded({
        processedCount: processedResults.length,
        processedPhotos: processedResults,
        previewItems: previewItems,
        downsampler: downsampler,
        downsampleTimeMs: totalDownsampleTimeMs
      });

    } catch (err) {
      console.error("[PhotoUploader] Downsampling error:", err);
      setProcessingStage('error');
      setIsProcessing(false);
      alert(`Photo processing failed: ${err.message}`);
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleChange = (e) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFiles(e.target.files);
    }
  };

  return (
    <div className="step-card">
      <div className="step-header">
        <h2>Step 1: Upload Your Photos</h2>
        <p>Select or drag & drop 20 to 200 photos (Phase 1 Dual-Payload Client Ingestion)</p>
      </div>

      {/* Live Ingestion Stepper Status */}
      {isProcessing && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.85rem 1.25rem',
          background: 'var(--px-brand-iris-subtle)',
          border: '1px solid var(--px-brand-iris-border)',
          borderRadius: '12px',
          marginBottom: '1.5rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Loader2 size={20} color="var(--px-brand-iris)" className="animate-spin" />
            <span style={{ fontWeight: 600, color: 'var(--px-brand-iris-active)', fontSize: '0.92rem' }}>
              Downsampling 512px thumbnails ({progressStats.completed} / {progressStats.total})...
            </span>
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--px-text-muted)', fontWeight: 500 }}>
            {Math.round((progressStats.completed / Math.max(1, progressStats.total)) * 100)}%
          </span>
        </div>
      )}

      {processingStage === 'ready' && !isProcessing && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.6rem',
          padding: '0.75rem 1.25rem',
          background: 'var(--px-status-success-bg)',
          border: '1px solid var(--px-status-success-border)',
          borderRadius: '12px',
          marginBottom: '1.5rem'
        }}>
          <CheckCircle2 size={18} color="var(--px-status-success-text)" />
          <span style={{ fontWeight: 600, color: 'var(--px-status-success-text)', fontSize: '0.9rem' }}>
            {localPhotos.length} Photos Prepared & Downsampled. Ready for AI Theme Selection!
          </span>
        </div>
      )}

      <div 
        className={`dropzone ${dragActive ? 'active' : ''}`}
        onDragEnter={handleDrag}
        onDragOver={handleDrag}
        onDragLeave={handleDrag}
        onDrop={handleDrop}
      >
        <UploadCloud size={48} color="var(--px-brand-iris)" strokeWidth={1.5} style={{ marginBottom: '1rem' }} />
        <h4 style={{ fontSize: '1.1rem', marginBottom: '0.5rem', color: 'var(--px-text-primary)' }}>
          Drag & drop photos here, or <span style={{ color: 'var(--px-brand-iris)', textDecoration: 'underline' }}>browse</span>
        </h4>
        <p style={{ color: 'var(--px-text-muted)', fontSize: '0.85rem' }}>
          {isProcessing ? "Processing 512px canvas downsampling..." : "Supports JPEG, PNG, WebP (20 to 200 photos)"}
        </p>
        
        <input 
          type="file" 
          multiple 
          accept="image/*"
          onChange={handleChange}
          style={{ display: 'none' }}
          id="file-upload-input"
          disabled={isProcessing || isUploading}
        />
        
        <label 
          htmlFor="file-upload-input" 
          className="btn btn-secondary"
          style={{ marginTop: '1.25rem', display: 'inline-flex', cursor: isProcessing ? 'not-allowed' : 'pointer' }}
        >
          {isProcessing ? "Downsampling..." : "Select Photos"}
        </label>
      </div>

      {localPhotos.length > 0 && (
        <div style={{ marginTop: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h4 style={{ fontWeight: 600, color: 'var(--px-text-primary)' }}>Prepared Photos ({localPhotos.length})</h4>
            <span style={{ fontSize: '0.82rem', color: 'var(--px-text-muted)' }}>512px Optimized Thumbnails</span>
          </div>

          <div className="photo-grid" style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
            gap: '0.75rem',
            maxHeight: '320px',
            overflowY: 'auto',
            padding: '0.5rem',
            background: 'var(--px-canvas-bg)',
            borderRadius: '12px',
            border: '1px solid var(--px-border-light)'
          }}>
            {localPhotos.map((p, idx) => (
              <div key={idx} className="photo-card" style={{
                position: 'relative',
                borderRadius: '8px',
                overflow: 'hidden',
                aspectRatio: '1',
                background: 'var(--px-border-subtle)'
              }}>
                <img 
                  src={p.previewUrl} 
                  alt={p.filename} 
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
