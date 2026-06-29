import React, { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, CheckCircle2, AlertCircle, UploadCloud } from 'lucide-react';
import { toast } from 'sonner';
import { useSdk } from '../../hooks/useSdk';

const STAGES = [
  { id: 'init', label: 'Initiate' },
  { id: 'upload', label: 'Upload parts' },
  { id: 'complete', label: 'Complete' },
  { id: 'verify', label: 'Verify' },
];

export default function EvidenceUpload() {
  const sdk = useSdk();
  const navigate = useNavigate();

  const [registryId, setRegistryId] = useState('');
  const [kind, setKind] = useState('document');
  const [file, setFile] = useState(null);

  const [stage, setStage] = useState(null);
  const [stageProgress, setStageProgress] = useState(0);
  const [error, setError] = useState(null);
  const [evidenceId, setEvidenceId] = useState(null);
  const [partReceipt, setPartReceipt] = useState(null);
  const [verification, setVerification] = useState(null);
  const busy = stage !== null && stage !== 'done' && stage !== 'error';

  const onUpload = useCallback(
    async (e) => {
      e.preventDefault();
      if (!file || !registryId.trim()) {
        toast.error('Registry id and file are required');
        return;
      }
      setError(null);
      setVerification(null);
      setPartReceipt(null);
      setEvidenceId(null);
      try {
        // 1. Initiate
        setStage('init');
        setStageProgress(10);
        const init = await sdk.evidence.initiateUpload({
          registry_id: registryId.trim(),
          kind,
          media_type: file.type || 'application/octet-stream',
          max_size: Math.max(file.size, 1024),
        });
        setEvidenceId(init.evidence_id);
        // 2. Upload one part (whole file as part 1 for the MVP)
        setStage('upload');
        setStageProgress(35);
        const bytes = await file.arrayBuffer();
        const receipt = await sdk.evidence.uploadPart(init.evidence_id, 1, bytes);
        setPartReceipt(receipt);
        // 3. Complete
        setStage('complete');
        setStageProgress(70);
        await sdk.evidence.completeUpload(init.evidence_id, {
          parts: [
            {
              part_no: 1,
              size_bytes: receipt.size_bytes,
              streamed_sha256: receipt.streamed_sha256 || receipt.sha256,
            },
          ],
        });
        // 4. Verify
        setStage('verify');
        setStageProgress(90);
        const item = await sdk.evidence.verify(init.evidence_id);
        setVerification(item);
        setStage('done');
        setStageProgress(100);
        toast.success('Evidence uploaded and verified');
      } catch (err) {
        setStage('error');
        const msg = err?.detail || err?.message || 'Upload failed';
        setError(msg);
        toast.error(msg);
      }
    },
    [file, registryId, kind, sdk]
  );

  return (
    <section data-testid="evidence-upload-section">
      <header className="mb-6">
        <h2 className="text-2xl font-medium text-slate-100">Upload Evidence</h2>
        <p className="text-sm text-slate-400 mt-1">
          Multipart upload → server-side hashing → projection-backed verification.
          The browser never computes authoritative hashes; the server is the
          source of truth.
        </p>
      </header>

      <form
        onSubmit={onUpload}
        className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8"
        data-testid="evidence-upload-form"
        aria-busy={busy ? 'true' : 'false'}
      >
        <label className="flex flex-col gap-2">
          <span className="text-sm text-slate-300">Registry ID</span>
          <input
            required
            type="text"
            value={registryId}
            onChange={(e) => setRegistryId(e.target.value)}
            placeholder="lv_…"
            data-testid="evidence-upload-registry"
            className="px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-md text-sm text-slate-100 font-mono placeholder:text-slate-600 focus:outline-none focus:border-amber-400/60 focus:ring-1 focus:ring-amber-400/40"
          />
        </label>
        <label className="flex flex-col gap-2">
          <span className="text-sm text-slate-300">Kind</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            data-testid="evidence-upload-kind"
            className="px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-md text-sm text-slate-100 focus:outline-none focus:border-amber-400/60"
          >
            <option value="document">document</option>
            <option value="image">image</option>
            <option value="survey">survey</option>
            <option value="legal">legal</option>
          </select>
        </label>
        <label className="md:col-span-2 flex flex-col gap-2">
          <span className="text-sm text-slate-300">File</span>
          <div className="flex items-center gap-3 px-3 py-3 bg-slate-900/80 border border-dashed border-slate-700 rounded-md">
            <UploadCloud className="w-5 h-5 text-amber-400" aria-hidden />
            <input
              required
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              data-testid="evidence-upload-file"
              className="flex-1 text-sm text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:bg-amber-400/10 file:text-amber-300 file:border file:border-amber-400/30 file:rounded file:hover:bg-amber-400/20 file:cursor-pointer"
            />
          </div>
        </label>
        <div className="md:col-span-2">
          <button
            type="submit"
            disabled={busy}
            data-testid="evidence-upload-submit"
            className="inline-flex items-center gap-2 px-4 py-2 bg-amber-400 text-slate-900 font-medium rounded-md hover:bg-amber-300 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}
            {busy ? 'Uploading…' : 'Upload + verify'}
          </button>
        </div>
      </form>

      {stage && (
        <ProgressBoard
          stage={stage}
          progress={stageProgress}
          error={error}
          evidenceId={evidenceId}
          receipt={partReceipt}
          verification={verification}
          onView={() => evidenceId && navigate(`/evidence/items/${evidenceId}`)}
        />
      )}
    </section>
  );
}

function ProgressBoard({
  stage,
  progress,
  error,
  evidenceId,
  receipt,
  verification,
  onView,
}) {
  return (
    <div
      data-testid="evidence-upload-progress"
      aria-live="polite"
      className="border border-slate-800 rounded-lg p-5 bg-slate-900/40"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-slate-200">Pipeline</h3>
        <span className="text-xs text-slate-400 font-mono" data-testid="upload-progress-pct">
          {progress}%
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden mb-5"
      >
        <div
          className="h-full bg-amber-400 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <ol className="space-y-2">
        {STAGES.map((s) => {
          const reached = STAGES.findIndex((x) => x.id === s.id) <=
            STAGES.findIndex((x) => x.id === (stage === 'done' ? 'verify' : stage));
          const done =
            stage === 'done' ||
            STAGES.findIndex((x) => x.id === s.id) <
              STAGES.findIndex((x) => x.id === stage);
          return (
            <li
              key={s.id}
              className="flex items-center gap-3 text-sm"
              data-testid={`stage-${s.id}`}
            >
              {done && stage !== 'error' && (
                <CheckCircle2 className="w-4 h-4 text-emerald-400" aria-hidden />
              )}
              {!done && reached && stage !== 'error' && (
                <Loader2 className="w-4 h-4 animate-spin text-amber-400" aria-hidden />
              )}
              {!reached && (
                <span className="w-4 h-4 rounded-full border border-slate-700" aria-hidden />
              )}
              {stage === 'error' && s.id === stage && (
                <AlertCircle className="w-4 h-4 text-rose-400" aria-hidden />
              )}
              <span className={reached ? 'text-slate-100' : 'text-slate-500'}>
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>

      {evidenceId && (
        <div className="mt-5 text-xs font-mono text-slate-400" data-testid="upload-evidence-id">
          evidence_id: <span className="text-slate-100">{evidenceId}</span>
        </div>
      )}
      {receipt && (
        <div className="mt-2 text-xs font-mono text-slate-400" data-testid="upload-part-receipt">
          part #{receipt.part_no} · {receipt.size_bytes} bytes · sha256
          <span className="text-slate-300 break-all"> {receipt.streamed_sha256 || receipt.sha256}</span>
        </div>
      )}
      {verification && (
        <div className="mt-2 text-xs text-emerald-300" data-testid="upload-verification">
          status: <span className="font-mono">{verification.status}</span>
          {verification.composite_sha256 && (
            <>
              {' · composite '}
              <span className="font-mono break-all">{verification.composite_sha256}</span>
            </>
          )}
        </div>
      )}
      {error && (
        <div className="mt-3 text-sm text-rose-300" role="alert" data-testid="upload-error">
          {error}
        </div>
      )}
      {stage === 'done' && (
        <button
          type="button"
          onClick={onView}
          data-testid="upload-view-evidence"
          className="mt-4 inline-flex items-center px-3 py-1.5 rounded border border-amber-400/40 text-amber-300 text-sm hover:bg-amber-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          View evidence
        </button>
      )}
    </div>
  );
}
