"""Chain-level constants: event signatures/topics, selectors, well-known contracts.

All values below were verified against Robinhood Chain (chain_id 4663) on 2026-09-02:
- PoolManager 0x8366...0951 emits the Uniswap v4 ``Swap``/``Initialize`` events.
- Tokens launched through Doppler are EIP-1167 clones of DopplerERC20V1.
"""
from __future__ import annotations

from intel.utils.abi import event_topic, selector

CHAIN_ID = 4663
DEXSCREENER_CHAIN = "robinhood"

# ---- events ---------------------------------------------------------------- #
SIG_TRANSFER = "Transfer(address,address,uint256)"
SIG_APPROVAL = "Approval(address,address,uint256)"
SIG_OWNERSHIP_TRANSFERRED = "OwnershipTransferred(address,address)"
SIG_V4_SWAP = "Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)"
SIG_V4_INITIALIZE = "Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)"
SIG_V4_MODIFY_LIQUIDITY = "ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)"
SIG_AIRLOCK_CREATE = "Create(address,address,address,address)"
SIG_AIRLOCK_MIGRATE = "Migrate(address,address)"

TOPIC_TRANSFER = event_topic(SIG_TRANSFER)
TOPIC_APPROVAL = event_topic(SIG_APPROVAL)
TOPIC_OWNERSHIP_TRANSFERRED = event_topic(SIG_OWNERSHIP_TRANSFERRED)
TOPIC_V4_SWAP = event_topic(SIG_V4_SWAP)
TOPIC_V4_INITIALIZE = event_topic(SIG_V4_INITIALIZE)
TOPIC_V4_MODIFY_LIQUIDITY = event_topic(SIG_V4_MODIFY_LIQUIDITY)
TOPIC_AIRLOCK_CREATE = event_topic(SIG_AIRLOCK_CREATE)
TOPIC_AIRLOCK_MIGRATE = event_topic(SIG_AIRLOCK_MIGRATE)

# ---- ERC-20 / ownership selectors ----------------------------------------- #
SEL_NAME = selector("name()")
SEL_SYMBOL = selector("symbol()")
SEL_DECIMALS = selector("decimals()")
SEL_TOTAL_SUPPLY = selector("totalSupply()")
SEL_BALANCE_OF = selector("balanceOf(address)")
SEL_OWNER = selector("owner()")
SEL_PAUSED = selector("paused()")
SEL_GET_OWNER = selector("getOwner()")

# EIP-1967 implementation / admin slots
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"

# Uniswap v4 dynamic-fee flag in PoolKey.fee
V4_DYNAMIC_FEE_FLAG = 0x800000

# Dangerous / privileged function signatures used by the security heuristics.
# Mapping: signature -> (category, severity) ; severity in {FAIL, WARN}
PRIVILEGED_SIGNATURES: dict[str, tuple[str, str]] = {
    "mint(address,uint256)": ("mint", "FAIL"),
    "mint(uint256)": ("mint", "FAIL"),
    "mintTo(address,uint256)": ("mint", "FAIL"),
    "mint(address,uint256,bytes)": ("mint", "FAIL"),
    "setBlacklist(address,bool)": ("blacklist", "FAIL"),
    "blacklist(address)": ("blacklist", "FAIL"),
    "addBlacklist(address)": ("blacklist", "FAIL"),
    "blacklistAddress(address,bool)": ("blacklist", "FAIL"),
    "setBlackList(address,bool)": ("blacklist", "FAIL"),
    "setBots(address[],bool)": ("blacklist", "FAIL"),
    "addBots(address[])": ("blacklist", "FAIL"),
    "setWhitelist(address,bool)": ("whitelist", "WARN"),
    "whitelist(address)": ("whitelist", "WARN"),
    "pause()": ("pause", "WARN"),
    "unpause()": ("pause", "WARN"),
    "setTradingEnabled(bool)": ("trading_switch", "WARN"),
    "enableTrading()": ("trading_switch", "WARN"),
    "setMaxTxAmount(uint256)": ("transfer_limit", "WARN"),
    "setMaxWallet(uint256)": ("transfer_limit", "WARN"),
    "setMaxWalletAmount(uint256)": ("transfer_limit", "WARN"),
    "setFee(uint256)": ("tax", "WARN"),
    "setFees(uint256,uint256)": ("tax", "WARN"),
    "setTaxes(uint256,uint256)": ("tax", "WARN"),
    "setBuyTax(uint256)": ("tax", "WARN"),
    "setSellTax(uint256)": ("tax", "WARN"),
    "updateFees(uint256,uint256)": ("tax", "WARN"),
    "setFeeExempt(address,bool)": ("tax", "WARN"),
    "excludeFromFee(address)": ("tax", "WARN"),
    "setSwapEnabled(bool)": ("sell_switch", "WARN"),
    "lockPool()": ("pool_lock", "WARN"),
    "unlockPool()": ("pool_lock", "WARN"),
    "upgradeTo(address)": ("upgradeable", "WARN"),
    "upgradeToAndCall(address,bytes)": ("upgradeable", "WARN"),
    "setImplementation(address)": ("upgradeable", "WARN"),
    "burnFrom(address,uint256)": ("burn_from", "WARN"),
    "rescueTokens(address,uint256)": ("rescue", "WARN"),
    "setBalanceLimit(uint256)": ("transfer_limit", "WARN"),
    "disableBalanceLimit()": ("transfer_limit", "WARN"),
}

DOPPLER_ERC20_VIEWS: dict[str, tuple[str, list[str]]] = {
    # name -> (signature, output types)
    "isBalanceLimitActive": ("isBalanceLimitActive()", ["bool"]),
    "maxBalanceLimit": ("maxBalanceLimit()", ["uint256"]),
    "balanceLimitEnd": ("balanceLimitEnd()", ["uint48"]),
    "isPoolLocked": ("isPoolLocked()", ["bool"]),
    "pool": ("pool()", ["address"]),
    "controller": ("controller()", ["address"]),
    "vestingScheduleCount": ("vestingScheduleCount()", ["uint256"]),
    "vestedTotalAmount": ("vestedTotalAmount()", ["uint256"]),
    "vestingStart": ("vestingStart()", ["uint256"]),
}

AIRLOCK_GET_ASSET_DATA = "getAssetData(address)"
AIRLOCK_GET_ASSET_DATA_OUTPUTS = ["address", "address", "address", "address", "address", "address", "address", "uint256", "uint256", "address"]
AIRLOCK_ASSET_DATA_FIELDS = ["numeraire", "timelock", "governance", "liquidity_migrator", "pool_initializer", "pool", "migration_pool", "num_tokens_to_sell", "total_supply", "integrator"]

# V4Quoter.quoteExactInputSingle((address,address,uint24,int24,address),bool,uint128,bytes) -> (uint256,uint256)
V4_QUOTE_EXACT_INPUT_SINGLE = "quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))"
STATE_VIEW_GET_SLOT0 = "getSlot0(bytes32)"
STATE_VIEW_GET_LIQUIDITY = "getLiquidity(bytes32)"
