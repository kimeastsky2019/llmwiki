package com.gng.channel.acct;

import java.util.List;
import java.util.Map;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 계좌 매퍼
 */
@Mapper("accountMapper")
public interface AccountMapper {

    Map<String, Object> selectCustomerSummary(@Param("custNo") String custNo);

    List<Map<String, Object>> selectAccountList(AccountVO searchVO);

    List<Map<String, Object>> selectTransactionList(AccountVO searchVO);

    long selectBalance(@Param("acctNo") String acctNo);

    int updateWithdraw(AccountVO transferVO);

    int updateDeposit(AccountVO transferVO);

    int insertTransaction(AccountVO transferVO);
}
