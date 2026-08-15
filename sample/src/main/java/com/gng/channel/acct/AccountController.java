package com.gng.channel.acct;

import java.util.List;
import java.util.Map;

import javax.annotation.Resource;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 내 계좌 조회
 *
 * 채널계(인터넷/모바일뱅킹)에서 로그인 고객의 계좌 목록과 잔액을 조회한다.
 * 고객 기본정보는 기관계와 동일한 TB_CUST 테이블을 참조한다.
 */
@RestController
@RequestMapping("/channel/acct")
public class AccountController {

    @Resource(name = "accountService")
    private AccountService accountService;

    /**
     * 내 계좌 목록 조회
     */
    @GetMapping("/myAccounts.json")
    public Map<String, Object> myAccounts(AccountVO searchVO) {
        return accountService.selectMyAccounts(searchVO);
    }

    /**
     * 계좌 거래내역 조회
     */
    @GetMapping("/transactions.json")
    public List<Map<String, Object>> transactions(AccountVO searchVO) {
        return accountService.selectTransactions(searchVO);
    }

    /**
     * 계좌 이체
     */
    @PostMapping("/transfer.json")
    public Map<String, Object> transfer(@RequestBody AccountVO transferVO) {
        return accountService.transfer(transferVO);
    }
}
