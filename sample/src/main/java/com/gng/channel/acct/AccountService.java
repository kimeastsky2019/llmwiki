package com.gng.channel.acct;

import java.util.List;
import java.util.Map;

/**
 * 계좌 서비스 인터페이스
 */
public interface AccountService {

    Map<String, Object> selectMyAccounts(AccountVO searchVO);

    List<Map<String, Object>> selectTransactions(AccountVO searchVO);

    Map<String, Object> transfer(AccountVO transferVO);
}
