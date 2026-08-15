package com.gng.common.code;

import java.util.List;
import java.util.Map;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 공통코드 매퍼
 */
@Mapper("codeMapper")
public interface CodeMapper {

    List<Map<String, Object>> selectCodeList(@Param("cdGrp") String cdGrp);

    String selectCodeName(@Param("cdGrp") String cdGrp, @Param("cd") String cd);
}
