pragma solidity 0.7.6;

import "./Mock.sol";

contract MockHelpCoinPolicy is Mock {
    function rebase() external {
        emit FunctionCalled("HelpCoinPolicy", "rebase", msg.sender);
    }
}
