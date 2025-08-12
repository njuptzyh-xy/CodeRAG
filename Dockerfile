FROM ubuntu:22.04  

RUN apt-get update && apt-get install -y \
    unzip \
    systemd \
    build-essential \
    wget \
    libsqlite3-dev \
    make \
    libssl-dev \
    vim \
    libffi-dev \
    python3 \
    zlib1g-dev \
    libbz2-dev \
    language-pack-zh-hans \
    liblzma-dev xz-utils libmagic1 unrar checksec    # 添加 xz-utils 支持 lzma 压缩

ENV PYTHON_VERSION=3.13.2

# python3
ENV PATH=$PATH:/usr/local/python313/bin
RUN wget https://mirrors.huaweicloud.com/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz
RUN tar -C /usr/local -xzf Python-${PYTHON_VERSION}.tgz \
    && rm -f Python-${PYTHON_VERSION}.tgz \
    && mkdir /usr/local/python313 \
    && cd /usr/local/Python-${PYTHON_VERSION} \
    && ./configure --prefix=/usr/local/python313 \
    && make && make install \
    && rm -rf /usr/local/Python-${PYTHON_VERSION}

RUN rm -rf /usr/bin/python3
RUN rm -rf /usr/bin/pip3

RUN ln -s /usr/local/python313/bin/python3.13 /usr/bin/python3
RUN ln -s /usr/local/python313/bin/pip3.13 /usr/bin/pip3

# 时区设置
ENV TZ=Asia/Shanghai
# 安装 OpenJDK 17
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata

#RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN dpkg-reconfigure -f noninteractive tzdata

# 将依赖包拷贝到 docker
ADD ./requirements.txt /requirements.txt
RUN apt-get update
RUN pip3 install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
RUN python3 -m pip install --upgrade setuptools -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
RUN pip3 install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r /requirements.txt


WORKDIR /home/neo4j-search
COPY . /home/neo4j-search/
RUN mkdir /home/logs

# RUN apt-get install language-pack-zh-hans
RUN localedef -c -f UTF-8 -i en_US en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANG=zh_CN.GB18030


# 设置启动命令
ENTRYPOINT ["python3", "/home/neo4j-search/create_app.py"]

# COPY start.sh /home/neo4j-search/start.sh
# RUN chmod +x /home/neo4j-search/start.sh
# ENTRYPOINT ["/home/neo4j-search/start.sh"]