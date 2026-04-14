"""Deep Reconstruction Autoencoder for Temporal Telemetry Anomaly Detection.

Implements a non-linear bottleneck neural autoencoder (d -> h1 -> z -> h2 -> d)
with LeakyReLU activations, vectorized Adam optimization, and feature-attribution scoring.

Trained exclusively on nominal baseline telemetry to detect complex non-linear
multi-metric drift via high reconstruction error (MSE).
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np


class ReconstructionAutoencoder:
    """Non-linear deep reconstruction autoencoder with analytical Adam backpropagation."""

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 16,
        latent_dim: int = 6,
        threshold_sigmas: float = 3.0,
        feature_names: Optional[List[str]] = None,
        seed: int = 42,
    ) -> None:
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.latent_dim = latent_dim
        self.threshold_sigmas = threshold_sigmas
        self.feature_names = feature_names or [f"feat_{i}" for i in range(input_dim)]
        self.rng = np.random.default_rng(seed)

        # Weight initialization (He / Kaiming normal for LeakyReLU)
        leaky_gain = np.sqrt(2.0 / (1.0 + 0.01**2))
        self.W1 = self.rng.normal(0, leaky_gain / np.sqrt(input_dim), (input_dim, hidden_dim))
        self.b1 = np.zeros(hidden_dim)

        self.W_enc = self.rng.normal(0, 1.0 / np.sqrt(hidden_dim), (hidden_dim, latent_dim))
        self.b_enc = np.zeros(latent_dim)

        self.W_dec = self.rng.normal(0, leaky_gain / np.sqrt(latent_dim), (latent_dim, hidden_dim))
        self.b_dec = np.zeros(hidden_dim)

        self.W2 = self.rng.normal(0, 1.0 / np.sqrt(hidden_dim), (hidden_dim, input_dim))
        self.b2 = np.zeros(input_dim)

        self.is_fitted: bool = False
        self.threshold: float = 1.0
        self.baseline_mean_loss: float = 0.0
        self.baseline_std_loss: float = 0.0

    @staticmethod
    def _leaky_relu(x: np.ndarray, alpha: float = 0.01) -> np.ndarray:
        return np.where(x > 0, x, x * alpha)

    @staticmethod
    def _leaky_relu_deriv(x: np.ndarray, alpha: float = 0.01) -> np.ndarray:
        return np.where(x > 0, 1.0, alpha)

    def _forward(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Forward pass through encoder and decoder."""
        a1 = X @ self.W1 + self.b1
        h1 = self._leaky_relu(a1)

        z = h1 @ self.W_enc + self.b_enc

        a2 = z @ self.W_dec + self.b_dec
        h2 = self._leaky_relu(a2)

        x_hat = h2 @ self.W2 + self.b2
        return a1, h1, z, a2, h2, x_hat

    def fit(
        self,
        X: np.ndarray,
        epochs: int = 50,
        batch_size: int = 32,
        lr: float = 0.005,
        verbose: bool = False,
    ) -> "ReconstructionAutoencoder":
        """Train autoencoder on nominal baseline vectors using Adam optimizer."""
        N, d = X.shape
        if d != self.input_dim:
            raise ValueError(f"Expected input_dim {self.input_dim}, got {d}")

        # Adam optimizer state
        params = [self.W1, self.b1, self.W_enc, self.b_enc, self.W_dec, self.b_dec, self.W2, self.b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        t = 0

        for _epoch in range(epochs):
            indices = np.arange(N)
            self.rng.shuffle(indices)

            for start in range(0, N, batch_size):
                end = min(N, start + batch_size)
                batch = X[indices[start:end]]
                B = batch.shape[0]

                # Forward Pass
                a1, h1, z, a2, h2, x_hat = self._forward(batch)

                # Output MSE loss gradient: dL/d(x_hat) = (x_hat - batch) / B
                d_xhat = (x_hat - batch) / B

                # Backpropagation through Decoder
                dW2 = h2.T @ d_xhat
                db2 = np.sum(d_xhat, axis=0)

                d_h2 = d_xhat @ self.W2.T
                d_a2 = d_h2 * self._leaky_relu_deriv(a2)

                dW_dec = z.T @ d_a2
                db_dec = np.sum(d_a2, axis=0)

                d_z = d_a2 @ self.W_dec.T

                # Backpropagation through Encoder
                dW_enc = h1.T @ d_z
                db_enc = np.sum(d_z, axis=0)

                d_h1 = d_z @ self.W_enc.T
                d_a1 = d_h1 * self._leaky_relu_deriv(a1)

                dW1 = batch.T @ d_a1
                db1 = np.sum(d_a1, axis=0)

                grads = [dW1, db1, dW_enc, db_enc, dW_dec, db_dec, dW2, db2]

                # Adam Parameter Updates
                t += 1
                for i in range(len(params)):
                    m[i] = beta1 * m[i] + (1.0 - beta1) * grads[i]
                    v[i] = beta2 * v[i] + (1.0 - beta2) * (grads[i] ** 2)
                    m_hat = m[i] / (1.0 - (beta1 ** t))
                    v_hat = v[i] / (1.0 - (beta2 ** t))
                    params[i] -= lr * m_hat / (np.sqrt(v_hat) + eps)

        # Calibrate anomaly threshold on training residuals
        *_, x_hat_all = self._forward(X)
        errors_per_sample = np.mean((X - x_hat_all) ** 2, axis=1)
        self.baseline_mean_loss = float(np.mean(errors_per_sample))
        self.baseline_std_loss = float(np.std(errors_per_sample)) + 1e-6
        self.threshold = self.baseline_mean_loss + (self.threshold_sigmas * self.baseline_std_loss)
        self.is_fitted = True
        return self

    def reconstruct(self, X: np.ndarray) -> np.ndarray:
        """Compute reconstructed matrix."""
        if not self.is_fitted:
            raise RuntimeError("Autoencoder must be fitted before reconstruction.")
        *_, x_hat = self._forward(X)
        return x_hat

    def score(
        self, x: np.ndarray
    ) -> Tuple[float, bool, float, Dict[str, float]]:
        """Score an observation vector.

        Returns:
            (reconstruction_mse, is_anomaly, z_deviation, feature_attributions)
        """
        if not self.is_fitted:
            raise RuntimeError("Autoencoder must be fitted before scoring.")

        vec = x.reshape(1, -1) if x.ndim == 1 else x
        *_, x_hat = self._forward(vec)

        sq_diff = (vec - x_hat) ** 2
        mse = float(np.mean(sq_diff))
        z_dev = float((mse - self.baseline_mean_loss) / self.baseline_std_loss)
        is_anomaly = mse >= self.threshold

        # Feature attribution: relative error contribution per metric
        total_err = float(np.sum(sq_diff)) + 1e-9
        attribution: Dict[str, float] = {}
        for name, err in zip(self.feature_names, sq_diff[0], strict=False):
            attribution[name] = round(float(err / total_err), 4)

        return mse, is_anomaly, z_dev, attribution

    def save_weights(self, filepath: Union[str, Path]) -> None:
        """Save network parameters and calibrated thresholds."""
        data = {
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "latent_dim": self.latent_dim,
            "threshold": self.threshold,
            "baseline_mean_loss": self.baseline_mean_loss,
            "baseline_std_loss": self.baseline_std_loss,
            "feature_names": self.feature_names,
            "W1": self.W1.tolist(),
            "b1": self.b1.tolist(),
            "W_enc": self.W_enc.tolist(),
            "b_enc": self.b_enc.tolist(),
            "W_dec": self.W_dec.tolist(),
            "b_dec": self.b_dec.tolist(),
            "W2": self.W2.tolist(),
            "b2": self.b2.tolist(),
        }
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @classmethod
    def load_weights(cls, filepath: Union[str, Path]) -> "ReconstructionAutoencoder":
        """Load network parameters and calibrated thresholds from JSON."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        ae = cls(
            input_dim=data["input_dim"],
            hidden_dim=data["hidden_dim"],
            latent_dim=data["latent_dim"],
            feature_names=data["feature_names"],
        )
        ae.threshold = data["threshold"]
        ae.baseline_mean_loss = data["baseline_mean_loss"]
        ae.baseline_std_loss = data["baseline_std_loss"]
        ae.W1 = np.array(data["W1"])
        ae.b1 = np.array(data["b1"])
        ae.W_enc = np.array(data["W_enc"])
        ae.b_enc = np.array(data["b_enc"])
        ae.W_dec = np.array(data["W_dec"])
        ae.b_dec = np.array(data["b_dec"])
        ae.W2 = np.array(data["W2"])
        ae.b2 = np.array(data["b2"])
        ae.is_fitted = True
        return ae
