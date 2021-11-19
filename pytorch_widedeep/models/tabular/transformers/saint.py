from torch import nn

from pytorch_widedeep.wdtypes import *  # noqa: F403
from pytorch_widedeep.models.embeddings_layers import (
    SameSizeCatAndContEmbeddings,
)
from pytorch_widedeep.models.tabular.mlp._layers import MLP
from pytorch_widedeep.models.tabular.transformers._encoders import SaintEncoder


class SAINT(nn.Module):
    r"""Defines a ``SAINT`` model
    (`arXiv:2106.01342 <https://arxiv.org/abs/2106.01342>`_) that can be used
    as the ``deeptabular`` component of a Wide & Deep model.

    Parameters
    ----------
    column_idx: Dict
        Dict containing the index of the columns that will be passed through
        the model. Required to slice the tensors. e.g.
        {'education': 0, 'relationship': 1, 'workclass': 2, ...}
    embed_input: List
        List of Tuples with the column name and number of unique values
        e.g. [('education', 11), ...]
    embed_dropout: float, default = 0.1
        Dropout to be applied to the embeddings matrix
    full_embed_dropout: bool, default = False
        Boolean indicating if an entire embedding (i.e. the representation of
        one column) will be dropped in the batch. See:
        :obj:`pytorch_widedeep.models.transformers._layers.FullEmbeddingDropout`.
        If ``full_embed_dropout = True``, ``embed_dropout`` is ignored.
    shared_embed: bool, default = False
        The idea behind ``shared_embed`` is described in the Appendix A in the
        `TabTransformer paper <https://arxiv.org/abs/2012.06678>`_: `'The
        goal of having column embedding is to enable the model to distinguish
        the classes in one column from those in the other columns'`. In other
        words, the idea is to let the model learn which column is embedded
        at the time.
    add_shared_embed: bool, default = False
        The two embedding sharing strategies are: 1) add the shared embeddings
        to the column embeddings or 2) to replace the first
        ``frac_shared_embed`` with the shared embeddings.
        See :obj:`pytorch_widedeep.models.transformers._layers.SharedEmbeddings`
    frac_shared_embed: float, default = 0.25
        The fraction of embeddings that will be shared (if ``add_shared_embed
        = False``) by all the different categories for one particular
        column.
    continuous_cols: List, Optional, default = None
        List with the name of the numeric (aka continuous) columns
    embed_continuous_activation: str, default = None
        String indicating the activation function to be applied to the
        continuous embeddings, if any. ``tanh``, ``relu``, ``leaky_relu`` and
        ``gelu`` are supported.
    cont_norm_layer: str, default =  None,
        Type of normalization layer applied to the continuous features before
        they are embedded. Options are: ``layernorm``, ``batchnorm`` or
        ``None``.
    input_dim: int, default = 32
        The so-called *dimension of the model*. In general is the number of
        embeddings used to encode the categorical and/or continuous columns
    n_heads: int, default = 8
        Number of attention heads per Transformer block
    use_bias: bool, default = False
        Boolean indicating whether or not to use bias in the Q, K, and V
        projection layers
    n_blocks: int, default = 2
        Number of SAINT-Transformer blocks. 1 in the paper.
    attn_dropout: float, default = 0.2
        Dropout that will be applied to the Multi-Head Attention column and
        row layers
    ff_dropout: float, default = 0.1
        Dropout that will be applied to the FeedForward network
    transformer_activation: str, default = "gelu"
        Transformer Encoder activation function. ``tanh``, ``relu``,
        ``leaky_relu``, ``gelu``, ``geglu`` and ``reglu`` are supported
    mlp_hidden_dims: List, Optional, default = None
        MLP hidden dimensions. If not provided it will default to ``[l, 4*l,
        2*l]`` where ``l`` is the MLP input dimension
    mlp_activation: str, default = "relu"
        MLP activation function. ``tanh``, ``relu``, ``leaky_relu`` and
        ``gelu`` are supported
    mlp_dropout: float, default = 0.1
        Dropout that will be applied to the final MLP
    mlp_batchnorm: bool, default = False
        Boolean indicating whether or not to apply batch normalization to the
        dense layers
    mlp_batchnorm_last: bool, default = False
        Boolean indicating whether or not to apply batch normalization to the
        last of the dense layers
    mlp_linear_first: bool, default = False
        Boolean indicating whether the order of the operations in the dense
        layer. If ``True: [LIN -> ACT -> BN -> DP]``. If ``False: [BN -> DP ->
        LIN -> ACT]``

    Attributes
    ----------
    cat_and_cont_embed: ``nn.Module``
        This is the module that processes the categorical and continuous columns
    transformer_blks: ``nn.Sequential``
        Sequence of SAINT-Transformer blocks
    transformer_mlp: ``nn.Module``
        MLP component in the model
    output_dim: int
        The output dimension of the model. This is a required attribute
        neccesary to build the WideDeep class

    Example
    --------
    >>> import torch
    >>> from pytorch_widedeep.models import SAINT
    >>> X_tab = torch.cat((torch.empty(5, 4).random_(4), torch.rand(5, 1)), axis=1)
    >>> colnames = ['a', 'b', 'c', 'd', 'e']
    >>> embed_input = [(u,i) for u,i in zip(colnames[:4], [4]*4)]
    >>> continuous_cols = ['e']
    >>> column_idx = {k:v for v,k in enumerate(colnames)}
    >>> model = SAINT(column_idx=column_idx, embed_input=embed_input, continuous_cols=continuous_cols)
    >>> out = model(X_tab)
    """

    def __init__(
        self,
        column_idx: Dict[str, int],
        cat_embed_input: Optional[List[Tuple[str, int]]] = None,
        cat_embed_dropout: float = 0.1,
        full_embed_dropout: bool = False,
        shared_embed: bool = False,
        add_shared_embed: bool = False,
        frac_shared_embed: float = 0.25,
        continuous_cols: Optional[List[str]] = None,
        embed_continuous_activation: str = None,
        cont_embed_dropout: float = 0.0,
        cont_embed_activation: str = None,
        cont_norm_layer: str = None,
        input_dim: int = 32,
        use_bias: bool = False,
        n_heads: int = 8,
        n_blocks: int = 2,
        attn_dropout: float = 0.1,
        ff_dropout: float = 0.2,
        transformer_activation: str = "gelu",
        mlp_hidden_dims: Optional[List[int]] = None,
        mlp_activation: str = "relu",
        mlp_dropout: float = 0.1,
        mlp_batchnorm: bool = False,
        mlp_batchnorm_last: bool = False,
        mlp_linear_first: bool = True,
    ):
        super(SAINT, self).__init__()

        self.column_idx = column_idx
        self.cat_embed_input = cat_embed_input
        self.cat_embed_dropout = cat_embed_dropout
        self.full_embed_dropout = full_embed_dropout
        self.shared_embed = shared_embed
        self.add_shared_embed = add_shared_embed
        self.frac_shared_embed = frac_shared_embed

        self.continuous_cols = continuous_cols
        self.embed_continuous_activation = embed_continuous_activation
        self.cont_embed_dropout = cont_embed_dropout
        self.cont_embed_activation = cont_embed_activation
        self.cont_norm_layer = cont_norm_layer

        self.input_dim = input_dim
        self.use_bias = use_bias
        self.n_heads = n_heads
        self.n_blocks = n_blocks
        self.attn_dropout = attn_dropout
        self.ff_dropout = ff_dropout
        self.transformer_activation = transformer_activation

        self.mlp_hidden_dims = mlp_hidden_dims
        self.mlp_activation = mlp_activation
        self.mlp_dropout = mlp_dropout
        self.mlp_batchnorm = mlp_batchnorm
        self.mlp_batchnorm_last = mlp_batchnorm_last
        self.mlp_linear_first = mlp_linear_first

        self.with_cls_token = "cls_token" in column_idx
        self.n_cat = len(cat_embed_input) if cat_embed_input is not None else 0
        self.n_cont = len(continuous_cols) if continuous_cols is not None else 0
        self.n_feats = self.n_cat + self.n_cont

        self.cat_and_cont_embed = SameSizeCatAndContEmbeddings(
            input_dim,
            column_idx,
            cat_embed_input,
            cat_embed_dropout,
            full_embed_dropout,
            shared_embed,
            add_shared_embed,
            frac_shared_embed,
            False,  # use_embed_bias
            continuous_cols,
            True,  # embed_continuous,
            cont_embed_dropout,
            embed_continuous_activation,
            True,  # use_cont_bias
            cont_norm_layer,
        )

        self.transformer_blks = nn.Sequential()
        for i in range(n_blocks):
            self.transformer_blks.add_module(
                "saint_block" + str(i),
                SaintEncoder(
                    input_dim,
                    n_heads,
                    use_bias,
                    attn_dropout,
                    ff_dropout,
                    transformer_activation,
                    self.n_feats,
                ),
            )

        attn_output_dim = (
            self.input_dim if self.with_cls_token else self.n_feats * self.input_dim
        )
        if not mlp_hidden_dims:
            mlp_hidden_dims = [
                attn_output_dim,
                attn_output_dim * 4,
                attn_output_dim * 2,
            ]
        else:
            mlp_hidden_dims = [attn_output_dim] + mlp_hidden_dims

        self.transformer_mlp = MLP(
            mlp_hidden_dims,
            mlp_activation,
            mlp_dropout,
            mlp_batchnorm,
            mlp_batchnorm_last,
            mlp_linear_first,
        )

        # the output_dim attribute will be used as input_dim when "merging" the models
        self.output_dim = mlp_hidden_dims[-1]

    def forward(self, X: Tensor) -> Tensor:

        x_cat, x_cont = self.cat_and_cont_embed(X)

        if x_cat is not None:
            x = x_cat
        if x_cont is not None:
            x = torch.cat([x, x_cont], 1) if x_cat is not None else x_cont

        x = self.transformer_blks(x)

        if self.with_cls_token:
            x = x[:, 0, :]
        else:
            x = x.flatten(1)

        return self.transformer_mlp(x)

    @property
    def attention_weights(self) -> List:
        r"""List with the attention weights. Each element of the list is a tuple
        where the first and the second elements are the column and row
        attention weights respectively

        The shape of the attention weights is:

            - column attention: :math:`(N, H, F, F)`

            - row attention: :math:`(1, H, N, N)`

        where *N* is the batch size, *H* is the number of heads and *F* is the
        number of features/columns in the dataset
        """
        attention_weights = []
        for blk in self.transformer_blks:
            attention_weights.append(
                (blk.col_attn.attn_weights, blk.row_attn.attn_weights)
            )
        return attention_weights
