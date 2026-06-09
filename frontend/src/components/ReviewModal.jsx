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
  const [gpt, setGpt] = useState('gpt-5.1');
  const [gemini, setGemini] = useState('gemini-3.1-pro');
  const [claude, setClaude] = useState('sonnet-4.6');
  const [grok, setGrok] = useState('grok-4.3');
  const [chairman, setChairman] = useState('gemini-3.1-pro');
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
    gpt,
    gemini,
    claude,
    grok,
    chairman,
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

        <label>Council models (choose per job)</label>
        <div className="model-grid">
          <select value={gpt} onChange={(e) => setGpt(e.target.value)}>
            <option value="gpt-5.1">GPT-5.1 (default)</option>
            <option value="gpt-5.2">GPT-5.2</option>
            <option value="gpt-5.5">GPT-5.5</option>
            <option value="gpt-5.5-pro">GPT-5.5 Pro — best</option>
          </select>
          <select value={gemini} onChange={(e) => setGemini(e.target.value)}>
            <option value="gemini-3.1-pro">Gemini 3.1 Pro (default)</option>
            <option value="gemini-3.5-flash">Gemini 3.5 Flash — value</option>
          </select>
          <select value={claude} onChange={(e) => setClaude(e.target.value)}>
            <option value="sonnet-4.6">Claude Sonnet 4.6 (default)</option>
            <option value="opus-4.6">Claude Opus 4.6</option>
            <option value="opus-4.7">Claude Opus 4.7</option>
            <option value="opus-4.8">Claude Opus 4.8 — best</option>
          </select>
          <select value={grok} onChange={(e) => setGrok(e.target.value)}>
            <option value="grok-4.3">Grok 4.3 (default)</option>
            <option value="grok-4.20">Grok 4.20</option>
          </select>
        </div>

        <label>Chairman — final synthesis</label>
        <select value={chairman} onChange={(e) => setChairman(e.target.value)}>
          <option value="gemini-3.1-pro">Gemini 3.1 Pro (default)</option>
          <option value="gpt-5.5">GPT-5.5</option>
          <option value="opus-4.8">Claude Opus 4.8</option>
          <option value="grok-4.3">Grok 4.3</option>
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
