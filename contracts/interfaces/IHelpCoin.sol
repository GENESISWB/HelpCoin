// pragma solidity ^0.4.24;

// Public interface definition for the IHelpCoin supply policy on Ethereum (the base-chain)
interface IIHelpCoin {
    function epoch() external view returns (uint256);

    function lastRebaseTimestampSec() external view returns (uint256);

    function inRebaseWindow() external view returns (bool);

    function globalIHelpCoinEpochAndAMPLSupply() external view returns (uint256, uint256);
}
