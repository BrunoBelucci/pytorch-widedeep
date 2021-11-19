import warnings

import numpy as np
import torch
from torch import nn

from pytorch_widedeep.wdtypes import *  # noqa: F403
from pytorch_widedeep.models.tabular.mlp._layers import MLP
from pytorch_widedeep.models.tabular.mlp._attention_layers import (
    ContextAttention,
)


class AttentiveRNN(nn.Module):
    r"""Standard text classifier/regressor comprised by a stack of RNNs
    (LSTMs or GRUs).

    In addition, there is the option to add a Fully Connected (FC) set of dense
    layers (referred as `attn_rnn_mlp`) on top of the stack of RNNs

    Parameters
    ----------
    vocab_size: int
        number of words in the vocabulary
    rnn_type: str, default = 'lstm'
        String indicating the type of RNN to use. One of ``lstm`` or ``gru``
    hidden_dim: int, default = 64
        Hidden dim of the RNN
    n_layers: int, default = 3
        number of recurrent layers
    rnn_dropout: float, default = 0.1
        dropout for the dropout layer on the outputs of each RNN layer except
        the last layer
    bidirectional: bool, default = True
        indicates whether the staked RNNs are bidirectional
    use_hidden_state: str, default = True
        Boolean indicating whether to use the final hidden state or the
        RNN output as predicting features
    padding_idx: int, default = 1
        index of the padding token in the padded-tokenised sequences. I
        use the ``fastai`` tokenizer where the token index 0 is reserved
        for the `'unknown'` word token
    embed_dim: int, Optional, default = None
        Dimension of the word embedding matrix if non-pretained word
        vectors are used
    embed_matrix: np.ndarray, Optional, default = None
         Pretrained word embeddings
    embed_trainable: bool, default = True
        Boolean indicating if the pretrained embeddings are trainable
    with_attention: bool, default = False
        Boolean indicating if attention will be used
    attn_concatenate: bool, default = True
        Boolean indicating if the input to the attention mechanism will be the
        output of the RNN or the output of the RNN concatenated with the last
        hidden state or simply
    attn_dropout: float, default = 0.1
        Internal dropout for the attention mechanism
    head_hidden_dims: List, Optional, default = None
        List with the sizes of the stacked dense layers in the head
        e.g: [128, 64]
    head_activation: str, default = "relu"
        Activation function for the dense layers in the head. Currently
        ``tanh``, ``relu``, ``leaky_relu`` and ``gelu`` are supported
    head_dropout: float, Optional, default = None
        dropout between the dense layers in the head
    head_batchnorm: bool, default = False
        Whether or not to include batch normalization in the dense layers that
        form the `'attn_rnn_mlp'`
    head_batchnorm_last: bool, default = False
        Boolean indicating whether or not to apply batch normalization to the
        last of the dense layers in the head
    head_linear_first: bool, default = False
        Boolean indicating whether the order of the operations in the dense
        layer. If ``True: [LIN -> ACT -> BN -> DP]``. If ``False: [BN -> DP ->
        LIN -> ACT]``

    Attributes
    ----------
    word_embed: ``nn.Module``
        word embedding matrix
    rnn: ``nn.Module``
        Stack of RNNs
    attn_rnn_mlp: ``nn.Sequential``
        Stack of dense layers on top of the RNN. This will only exists if
        ``head_layers_dim`` is not ``None``
    output_dim: int
        The output dimension of the model. This is a required attribute
        neccesary to build the WideDeep class

    Example
    --------
    >>> import torch
    >>> from pytorch_widedeep.models import RNN
    >>> X_text = torch.cat((torch.zeros([5,1]), torch.empty(5, 4).random_(1,4)), axis=1)
    >>> model = DeepText(vocab_size=4, hidden_dim=4, n_layers=1, padding_idx=0, embed_dim=4)
    >>> out = model(X_text)
    """

    def __init__(
        self,
        vocab_size: int,
        rnn_type: str = "lstm",
        hidden_dim: int = 64,
        n_layers: int = 3,
        rnn_dropout: float = 0.1,
        bidirectional: bool = False,
        use_hidden_state: bool = True,
        padding_idx: int = 1,
        embed_dim: Optional[int] = None,
        embed_matrix: Optional[np.ndarray] = None,
        embed_trainable: bool = True,
        with_attention: bool = False,
        attn_concatenate: bool = True,
        attn_dropout: float = 0.1,
        head_hidden_dims: Optional[List[int]] = None,
        head_activation: str = "relu",
        head_dropout: Optional[float] = None,
        head_batchnorm: bool = False,
        head_batchnorm_last: bool = False,
        head_linear_first: bool = False,
    ):
        super(AttentiveRNN, self).__init__()

        if (
            embed_dim is not None
            and embed_matrix is not None
            and not embed_dim == embed_matrix.shape[1]
        ):
            warnings.warn(
                "the input embedding dimension {} and the dimension of the "
                "pretrained embeddings {} do not match. The pretrained embeddings "
                "dimension ({}) will be used".format(
                    embed_dim, embed_matrix.shape[1], embed_matrix.shape[1]
                ),
                UserWarning,
            )

        if rnn_type.lower() not in ["lstm", "gru"]:
            raise ValueError(
                f"'rnn_type' must be 'lstm' or 'gru', got {rnn_type} instead"
            )

        self.vocab_size = vocab_size
        self.rnn_type = rnn_type
        self.hidden_dim = hidden_dim
        self.n_layers = n_layers
        self.rnn_dropout = rnn_dropout
        self.bidirectional = bidirectional
        self.use_hidden_state = use_hidden_state
        self.padding_idx = padding_idx
        self.embed_dim = embed_dim
        self.embed_trainable = embed_trainable

        self.with_attention = with_attention
        self.attn_concatenate = attn_concatenate
        self.attn_dropout = attn_dropout

        self.head_hidden_dims = head_hidden_dims
        self.head_activation = head_activation
        self.head_dropout = head_dropout
        self.head_batchnorm = head_batchnorm
        self.head_batchnorm_last = head_batchnorm_last
        self.head_linear_first = head_linear_first

        # Pre-trained Embeddings
        self.word_embed, embed_dim = self._set_embeddings(embed_matrix)

        # stack of RNNs (LSTMs)
        rnn_params = {
            "input_size": embed_dim,
            "hidden_size": hidden_dim,
            "num_layers": n_layers,
            "bidirectional": bidirectional,
            "dropout": rnn_dropout,
            "batch_first": True,
        }
        if self.rnn_type.lower() == "lstm":
            self.rnn: Union[nn.LSTM, nn.GRU] = nn.LSTM(**rnn_params)
        elif self.rnn_type.lower() == "gru":
            self.rnn = nn.GRU(**rnn_params)

        # Attention
        if self.with_attention:
            if bidirectional and attn_concatenate:
                attn_input_dim = hidden_dim * 4
            elif bidirectional or attn_concatenate:
                attn_input_dim = hidden_dim * 2
            else:
                attn_input_dim = hidden_dim
            self.attn = ContextAttention(
                attn_input_dim, attn_dropout, sum_along_seq=True
            )
            self.output_dim = attn_input_dim
        else:
            self.output_dim = hidden_dim * 2 if bidirectional else hidden_dim

        if self.head_hidden_dims is not None:
            head_hidden_dims = [self.output_dim] + head_hidden_dims
            self.attn_rnn_mlp = MLP(
                head_hidden_dims,
                head_activation,
                head_dropout,
                head_batchnorm,
                head_batchnorm_last,
                head_linear_first,
            )
            self.output_dim = head_hidden_dims[-1]

    def forward(self, X: Tensor) -> Tensor:  # type: ignore
        embed = self.word_embed(X.long())

        if self.rnn_type.lower() == "lstm":
            o, (h, c) = self.rnn(embed)
        elif self.rnn_type.lower() == "gru":
            o, h = self.rnn(embed)

        processed_outputs = self._process_rnn_outputs(o, h)

        if self.head_hidden_dims is not None:
            head_out = self.attn_rnn_mlp(processed_outputs)
            return head_out
        else:
            return processed_outputs

    def _set_embeddings(
        self, embed_matrix: Union[Any, np.ndarray]
    ) -> Tuple[nn.Module, int]:
        if isinstance(embed_matrix, np.ndarray):
            assert (
                embed_matrix.dtype == "float32"
            ), "'embed_matrix' must be of dtype 'float32', got dtype '{}'".format(
                str(embed_matrix.dtype)
            )
            word_embed = nn.Embedding(
                self.vocab_size, embed_matrix.shape[1], padding_idx=self.padding_idx
            )
            if self.embed_trainable:
                word_embed.weight = nn.Parameter(
                    torch.tensor(embed_matrix), requires_grad=True
                )
            else:
                word_embed.weight = nn.Parameter(
                    torch.tensor(embed_matrix), requires_grad=False
                )
            embed_dim = embed_matrix.shape[1]
        else:
            word_embed = nn.Embedding(
                self.vocab_size, embed_dim, padding_idx=self.padding_idx
            )
        return word_embed, embed_dim

    def _process_rnn_outputs(self, output: Tensor, hidden: Tensor) -> Tensor:
        if self.with_attention:
            if self.attn_concatenate:
                if self.bidirectional:
                    bi_hidden = torch.cat((hidden[-2], hidden[-1]), dim=1)
                    attn_inp = torch.cat(
                        [output, bi_hidden.unsqueeze(1).expand_as(output)], dim=2
                    )
            else:
                attn_inp = torch.cat(
                    [output, hidden[-1].unsqueeze(1).expand_as(output)], dim=2
                )
            processed_outputs = self.attn(attn_inp)
        else:
            output = output.permute(1, 0, 2)
            if self.bidirectional:
                processed_outputs = (
                    torch.cat((hidden[-2], hidden[-1]), dim=1)
                    if self.use_hidden_state
                    else output[-1]
                )
            else:
                processed_outputs = hidden[-1] if self.use_hidden_state else output[-1]

        return processed_outputs
