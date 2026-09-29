import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud, CheckCircle2, Loader2 } from 'lucide-react';
import PixovoClientDownsampler from '../utils/client_downsampler';
import PhotoFrame from './PhotoFrame';

const MAX_PREVIEW_TILES = 60;

/**
 * Phase 1 & Stage 2.1/2.3 Ingestion Pipeline Component:
 * - OffscreenCanvas Web Worker pool downsampling (512px thumbnails) + EXIF/GPS extraction
 * - Bounded preview grid (capped at 60 tiles with +N more indicator)
 * - Hands local preview URLs to App.jsx for optimistic instant rendering during ingest
 */
export default function PhotoUploader({ onPhotosUploaded, isUploading }) {
  const [dragActive, setDragActive] = useState(false);
  const [localPhotos, setLocalPhotos] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStage, setProcessingStage] = useState(''); // 'downsampling' | 'ready' | 'error'
  const [progressStats, setProgressStats] = useState({ completed: 0, total: 0 });

  // Stage 2.1 Task 5: Hoist downsampler instance into a ref so worker pool is reused
  // across renders and terminated cleanly on unmount.
  const downsamplerRef = useRef(null);
  if (!downsamplerRef.current) {
    downsamplerRef.current = new PixovoClientDownsampler({
      maxDimension: 512,
      quality: 0.85
    });
  }

  useEffect(() => {
    return () => {
      downsamplerRef.current?.terminate();
    };
  }, []);

  const handleFiles = async (files) => {
    if (!files || files.length === 0) return;
    const fileList = Array.from(files).filter(
      f => f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic|tiff)$/i.test(f.name)
    );

    if (fileList.length === 0) {
      alert('Please upload valid image files (JPG, PNG, WebP).');
      return;
    }

    setIsProcessing(true);
    setProcessingStage('downsampling');
    setProgressStats({ completed: 0, total: fileList.length });

    const downsampleStartTime = performance.now();
    try {
      const downsampler = downsamplerRef.current;

      // 1. Worker-backed non-blocking batch downsampling & EXIF/GPS extraction
      const processedResults = await downsampler.processBatch(fileList, (completed, total) => {
        setProgressStats({ completed, total });
      });

      if (!processedResults || processedResults.length === 0) {
        throw new Error('No valid photos could be processed.');
      }

      const totalDownsampleTimeMs = performance.now() - downsampleStartTime;

      // Revoke any previous local-only URLs if re-uploading on the same screen
      localPhotos.forEach(p => {
        if (p.previewUrl && p._ownedByUploader) {
          URL.revokeObjectURL(p.previewUrl);
        }
      });

      // 2. Build local preview items for optimistic UI feedback (Stage 2.3 Task 1)
      const previewItems = processedResults.map(p => ({
        photo_id: p.photo_id,
        filename: p.filename,
        aspect_ratio: p.aspect_ratio,
        previewUrl: p.thumbnail_blob ? URL.createObjectURL(p.thumbnail_blob) : '',
        originalFile: p.original_file,
        thumbnailBlob: p.thumbnail_blob
      }));

      setLocalPhotos(previewItems);
      setProcessingStage('ready');
      setIsProcessing(false);

      // 3. Hand processed photos + optimistic preview items to App.jsx
      onPhotosUploaded({
        processedCount: processedResults.length,
        processedPhotos: processedResults,
        previewItems: previewItems,
        downsampler: downsampler,
        downsampleTimeMs: totalDownsampleTimeMs
      });
    } catch (err) {
      console.error('[PhotoUploader] Downsampling error:', err);
      setProcessingStage('error');
      setIsProcessing(false);
      alert(`Photo processing failed: ${err.message}`);
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
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

  const visiblePhotos = localPhotos.slice(0, MAX_PREVIEW_TILES);
  const overflowCount = Math.max(0, localPhotos.length - MAX_PREVIEW_TILES);

  return (
    <div className="step-card">
      <div className="step-header">
        <h2>Step 1: Upload Your Photos</h2>
        <p>Select or drag & drop up to 1,000 photos (Worker-Accelerated 512px Client Ingestion)</p>
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
              Downsampling 512px thumbnails — {progressStats.completed} of {progressStats.total}
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
          {isProcessing ? 'Processing 512px worker downsampling...' : 'Supports JPEG, PNG, WebP (20 to 1,000 photos)'}
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
          {isProcessing ? 'Downsampling...' : 'Select Photos'}
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
            {visiblePhotos.map((p) => (
              <PhotoFrame
                key={p.photo_id}
                src={p.previewUrl}
                aspectRatio={1}
                alt={p.filename}
                className="photo-card"
                style={{ borderRadius: '8px' }}
              />
            ))}
            {overflowCount > 0 && (
              <div
                className="photo-card"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  aspectRatio: '1',
                  borderRadius: '8px',
                  background: 'var(--px-brand-iris-subtle)',
                  border: '1px solid var(--px-brand-iris-border)',
                  color: 'var(--px-brand-iris-active)',
                  fontWeight: 700,
                  fontSize: '0.9rem'
                }}
              >
                +{overflowCount} more
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
