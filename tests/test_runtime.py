"""Optional real-runtime regression checks, using a tiny synthetic checkpoint."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('torch', 'transformers', 'safetensors')), 'Install local model dependencies to test the runtime')
class CheckpointLoading(unittest.TestCase):
    def test_half_precision_checkpoint_restores_cpu_weights_and_rotary_buffers(self):
        import torch
        from safetensors.torch import save_file
        from transformers import ModernBertConfig
        from ticket_engine._vendor.laya.agent import Agent
        from ticket_engine._vendor.laya.common import build_model

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = ModernBertConfig(hidden_size=32, intermediate_size=32, num_hidden_layers=1, num_attention_heads=4, vocab_size=32, pad_token_id=0, bos_token_id=1, eos_token_id=2, cls_token_id=1, sep_token_id=2)
            config.save_pretrained(root / 'encoder')
            cfg = {'encoder': 'synthetic-test', 'head_layers': 0, 'act_costs': {}}
            (root / 'rl_agent_config.json').write_text(json.dumps(cfg))
            with torch.device('meta'):
                skeleton = build_model(cfg, str(root / 'encoder'))
            weights = {key: torch.full(tensor.shape, 0.25, dtype=torch.float16) for key, tensor in skeleton.state_dict().items()}
            save_file(weights, str(root / 'model.safetensors'))
            with patch('transformers.AutoTokenizer.from_pretrained', return_value=object()):
                agent = Agent(str(root), device='cpu')
            self.assertTrue(all(t.device.type == 'cpu' for t in list(agent.model.parameters()) + list(agent.model.buffers())))
            self.assertTrue(all(p.dtype == torch.float32 for p in agent.model.parameters()))
            for key, tensor in agent.model.state_dict().items():
                self.assertTrue(torch.equal(tensor, weights[key].float()), key)
            with torch.inference_mode():
                logits, _ = agent.model(torch.tensor([[1, 2, 3]]), torch.ones(1, 3, dtype=torch.long), torch.tensor([[0, 1]]), torch.ones(1, 2, dtype=torch.bool), torch.tensor([0]))
            self.assertTrue(torch.isfinite(logits).all())
            # Missing parameters still fail strictly; no initialized fallback.
            del weights['scorer.0.weight']
            save_file(weights, str(root / 'model.safetensors'))
            with patch('transformers.AutoTokenizer.from_pretrained', return_value=object()), self.assertRaises(ValueError):
                Agent(str(root), device='cpu')


if __name__ == '__main__':
    unittest.main()
