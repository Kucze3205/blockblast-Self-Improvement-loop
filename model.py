import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import os
import copy

from pieces import PIECE_GRID


class CustomNet(nn.Module):
    def __init__(self, num_numeric=4, output_dim=192):
        super().__init__()

        # Gałąź 1: CNN dla planszy (4 kanały: board + 3 weighted maski)
        self.board_cnn = nn.Sequential(
            nn.Conv2d(4, 32, 3, padding=1),
            nn.GroupNorm(32, 32),
            nn.ReLU(),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.GroupNorm(64, 64),
            nn.ReLU(),
            nn.Flatten(),
            nn.Linear(64 * 8 * 8, 256),
            nn.ReLU()
        )

        # MLP zamiast CNN — 4x4 to za mało dla konwolucji
        self.piece_mlp = nn.Sequential(
            nn.Flatten(),
            nn.Linear(PIECE_GRID * PIECE_GRID, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU()
        )

        # Gałąź 3: MLP dla cech heurystycznych
        self.numeric_mlp = nn.Sequential(
            nn.Linear(num_numeric, 64),
            nn.LayerNorm(64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU()
        )

        # Wspólna warstwa łącząca: 256 + 3*64 + 64 = 512
        self.shared_fc = nn.Sequential(
            nn.Linear(512, 512),
            nn.ReLU(),
            nn.Dropout(0.2)
        )

        # Dueling streams
        self.value_stream = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, 1)
        )
        self.advantage_stream = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, output_dim)
        )

    def forward(self, board, pieces, numeric):
        board_feat = self.board_cnn(board)
        piece_feats = [self.piece_mlp(p) for p in pieces]
        piece_feat = torch.cat(piece_feats, dim=1)
        numeric_feat = self.numeric_mlp(numeric)

        x = torch.cat([board_feat, piece_feat, numeric_feat], dim=1)
        x = self.shared_fc(x)

        value = self.value_stream(x)
        advantage = self.advantage_stream(x)

        q = value + (advantage - advantage.mean(dim=1, keepdim=True))
        return q

    def save(self, file_name='model.pth'):
        model_folder_path = './model'
        try:
            if not os.path.exists(model_folder_path):
                os.makedirs(model_folder_path)
            file_name = os.path.join(model_folder_path, file_name)
            torch.save(self.state_dict(), file_name)
        except Exception as e:
            print(f"[ERROR] Model save failed: {e}")


class QTrainer:
    def __init__(self, model, lr, gamma, target_update_freq=1000):
        self.model = model
        self.lr = lr
        self.gamma = gamma
        self.steps = 0
        self.target_update_freq = target_update_freq

        # --- TARGET NETWORK (kluczowa zmiana z papieru) ---
        # Oddzielna sieć do obliczania Q(s', a') w równaniu Bellmana.
        # Wagi zamrożone, aktualizowane co target_update_freq kroków.
        # Bez tego: sieć goni samą siebie → oscylacje → dywergencja.
        self.target_model = copy.deepcopy(model)
        self.target_model.load_state_dict(model.state_dict())
        # target_model NIGDY nie jest trenowany przez optimizer
        for param in self.target_model.parameters():
            param.requires_grad = False

        self.optimizer = optim.Adam(model.parameters(), lr=lr)

    def _sync_target(self):
        """Kopiuje wagi z modelu online do target network."""
        self.target_model.load_state_dict(self.model.state_dict())

    def train_step(self, state, action, reward, next_state, done):
        device = next(self.model.parameters()).device

        if isinstance(state, tuple) and isinstance(state[0], np.ndarray):
            # --- Tryb pojedynczy (short-term) ---
            grid, shapes, numeric, _ = state
            next_grid, next_shapes, next_numeric, _ = next_state

            grid        = torch.tensor(grid,    dtype=torch.float32, device=device).unsqueeze(0)
            shapes      = [torch.tensor(s,      dtype=torch.float32, device=device).unsqueeze(0) for s in shapes]
            numeric     = torch.tensor(numeric, dtype=torch.float32, device=device).unsqueeze(0)

            next_grid   = torch.tensor(next_grid,    dtype=torch.float32, device=device).unsqueeze(0)
            next_shapes = [torch.tensor(s,           dtype=torch.float32, device=device).unsqueeze(0) for s in next_shapes]
            next_numeric= torch.tensor(next_numeric, dtype=torch.float32, device=device).unsqueeze(0)

            reward = torch.tensor(reward, dtype=torch.float32, device=device).unsqueeze(0)
            action = torch.tensor(action, dtype=torch.long,    device=device).unsqueeze(0)
            done   = (done,)

        else:
            # --- Tryb batch (long-term) ---
            grids, shapes_list, numerics, _             = zip(*state)
            next_grids, next_shapes_list, next_numerics, _ = zip(*next_state)

            grid        = torch.tensor(np.array(grids),    dtype=torch.float32, device=device)
            shapes      = [torch.tensor(np.array(s),       dtype=torch.float32, device=device) for s in zip(*shapes_list)]
            numeric     = torch.tensor(np.array(numerics), dtype=torch.float32, device=device)

            next_grid   = torch.tensor(np.array(next_grids),    dtype=torch.float32, device=device)
            next_shapes = [torch.tensor(np.array(s),            dtype=torch.float32, device=device) for s in zip(*next_shapes_list)]
            next_numeric= torch.tensor(np.array(next_numerics), dtype=torch.float32, device=device)

            reward = torch.tensor(reward, dtype=torch.float32, device=device)
            action = torch.tensor(action, dtype=torch.long,    device=device)
            done   = torch.tensor(done,   dtype=torch.bool,    device=device)

        shapes      = [s.unsqueeze(1) for s in shapes]
        next_shapes = [s.unsqueeze(1) for s in next_shapes]

        # --- Predykcja online modelu ---
        self.model.train()
        pred = self.model(grid, shapes, numeric)
        target = pred.clone().detach()

        # --- TARGET NETWORK: oblicz Q(s', a') zamrożoną siecią ---
        # (paper eq. 3: θ_{i-1} są zamrożone przy optymalizacji L_i(θ_i))
        self.target_model.eval()
        with torch.no_grad():
            next_q_all = self.target_model(
                next_grid,
                next_shapes,
                next_numeric
            )                                          # [batch, 192]

        flat_indices = []
        for idx in range(len(done)):
            Q_new = reward[idx]
            if not done[idx]:
                # Używamy target_model zamiast self.model — kluczowa różnica
                Q_new = reward[idx] + self.gamma * torch.max(next_q_all[idx])

            piece_idx, x, y = action[idx][0], action[idx][1], action[idx][2]
            flat_idx = int(piece_idx) * 64 + int(y) * 8 + int(x)
            target[idx][flat_idx] = Q_new
            flat_indices.append(flat_idx)

        # --- Huber loss tylko dla wybranej akcji (gather) ---
        # Zamiast liczyć loss po całym wektorze 192 (gdzie 191/192 to kopia pred → gradient≈0
        # i advantage_stream nie dostaje sygnału), zbieramy tylko wybrany indeks.
        flat_indices_t = torch.tensor(flat_indices, dtype=torch.long, device=device)
        pred_selected   = pred.gather(1, flat_indices_t.unsqueeze(1)).squeeze(1)
        target_selected = target.gather(1, flat_indices_t.unsqueeze(1)).squeeze(1)
        loss = F.huber_loss(pred_selected, target_selected)

        self.optimizer.zero_grad()
        loss.backward()

        # --- Gradient clipping (paper nie wymienia, ale stabilizuje trening) ---
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=10.0)

        self.optimizer.step()

        # --- Synchronizacja target network co N kroków ---
        self.steps += 1
        if self.steps % self.target_update_freq == 0:
            self._sync_target()