import { useState } from 'react';
import { api } from '../api';
import './ReviewModal.css';

export default function ReviewModal({ onRun, onClose, isRunning }) {
  const [path, setPath] = useState('');
  const [question, setQuestion] = useState('');
  const [include, setInclude] = useState('');
  const [exclude, setExclude] = useState('');
  const [maxKB, setMaxKB] = useState(200);
  const [simple, setSimple] = useState(false);
  const [claude, setClaude] = useState('sonnet-4.6');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [previewing, setPreviewing] = useState(false);

  const buildParams = () => ({
    path: path.trim(),
    question: question.trim(),
    include: include.split(',').map((s) => s.trim()).filter(Boolean),
    exclude: exclude.split(',').map((s) => s.trim()).filter(Boolean),
    max_bytes: Math.round(Number(maxKB) * 1024) || 200000,
    simple,
    claude,
  });

  const handlePreview = async () => {
    setError('');
    setPreview(null);
    if (!path.trim()) {
      setError('Enter a project folder path.');
      return;
    }
    setPreviewing(true);
    try {
      const data = await api.reviewPreview(buildParams());
      if (data.error) setError(data.error);
      else setPreview(data);
    } catch (e) {
      setError('Preview failed: ' + e.message);
    } finally {
      setPreviewing(false);
    }
  };

  const handleRun = () => {
    if (!path.trim()) {
      setError('Enter a project folder path.');
      return;
    }
    onRun(buildParams());
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Review a Project</h2>

        <label>Project folder path</label>
        <input
          type="text"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="C:\path\to\your\project"
        />

        <label>Question (optional)</label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={2}
          placeholder="Default: a general code review"
        />

        <label>Claude model (choose per job)</label>
        <select value={claude} onChange={(e) => setClaude(e.target.value)}>
          <option value="sonnet-4.6">Claude Sonnet 4.6 — value (default)</option>
          <option value="opus-4.6">Claude Opus 4.6</option>
          <option value="opus-4.7">Claude Opus 4.7</option>
          <option value="opus-4.8">Claude Opus 4.8 — best</option>
        </select>

        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={simple}
            onChange={(e) => setSimple(e.target.checked)}
          />
          Explain simply (short, non-technical answer)
        </label>

        <button
          type="button"
          className="link-btn"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? 'Hide' : 'Show'} advanced options
        </button>

        {showAdvanced && (
          <div className="advanced">
            <label>Include globs (comma-separated)</label>
            <input
              type="text"
              value={include}
              onChange={(e) => setInclude(e.target.value)}
              placeholder="src/**/*.py, *.js"
            />
            <label>Exclude globs (comma-separated)</label>
            <input
              type="text"
              value={exclude}
              onChange={(e) => setExclude(e.target.value)}
              placeholder="*.test.js"
            />
            <label>Max total size (KB)</label>
            <input
              type="number"
              value={maxKB}
              onChange={(e) => setMaxKB(e.target.value)}
            />
          </div>
        )}

        {error && <div className="modal-error">{error}</div>}

        {preview && (
          <div className="modal-preview">
            <div>
              <strong>{preview.file_count}</strong> files,{' '}
              {(preview.total_bytes / 1024).toFixed(1)} KB
              {preview.skipped_count > 0 &&
                ` (${preview.skipped_count} skipped)`}
            </div>
            <div>
              ~{preview.est_tokens} tokens · est. cost ~${preview.est_cost}
            </div>
            <div className="preview-files">
              {preview.files.slice(0, 30).map((f) => (
                <div key={f}>{f}</div>
              ))}
              {preview.files.length > 30 && (
                <div>…and {preview.files.length - 30} more</div>
              )}
            </div>
          </div>
        )}

        <div className="modal-actions">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            type="button"
            onClick={handlePreview}
            className="btn-secondary"
            disabled={previewing || isRunning}
          >
            {previewing ? 'Previewing…' : 'Preview'}
          </button>
          <button
            type="button"
            onClick={handleRun}
            className="btn-primary"
            disabled={isRunning}
          >
            {isRunning ? 'Running…' : 'Run review'}
          </button>
        </div>
      </div>
    </div>
  );
}
