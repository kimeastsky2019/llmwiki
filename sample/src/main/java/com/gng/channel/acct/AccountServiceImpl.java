package com.gng.channel.acct;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.annotation.Resource;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 계좌 서비스 구현
 *
 * 이체는 출금 → 입금 → 거래내역 적재 순으로 처리하며 하나라도 실패하면 롤백한다.
 */
@Service("accountService")
public class AccountServiceImpl implements AccountService {

    @Resource(name = "accountMapper")
    private AccountMapper accountMapper;

    @Override
    public Map<String, Object> selectMyAccounts(AccountVO searchVO) {
        Map<String, Object> result = new HashMap<String, Object>();
        result.put("customer", accountMapper.selectCustomerSummary(searchVO.getCustNo()));
        result.put("accounts", accountMapper.selectAccountList(searchVO));
        return result;
    }

    @Override
    public List<Map<String, Object>> selectTransactions(AccountVO searchVO) {
        return accountMapper.selectTransactionList(searchVO);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> transfer(AccountVO transferVO) {
        Map<String, Object> result = new HashMap<String, Object>();

        long balance = accountMapper.selectBalance(transferVO.getAcctNo());
        if (balance < transferVO.getTrnAmt()) {
            result.put("code", "ACCT-E101");
            result.put("message", "잔액이 부족합니다.");
            return result;
        }

        int withdrawn = accountMapper.updateWithdraw(transferVO);
        if (withdrawn == 0) {
            throw new IllegalStateException("출금 처리에 실패했습니다.");
        }

        int deposited = accountMapper.updateDeposit(transferVO);
        if (deposited == 0) {
            throw new IllegalStateException("입금 처리에 실패했습니다.");
        }

        accountMapper.insertTransaction(transferVO);

        result.put("code", "0000");
        return result;
    }
}
